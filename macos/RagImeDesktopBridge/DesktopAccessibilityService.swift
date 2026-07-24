import AppKit
import ApplicationServices
import Carbon
import CoreGraphics
import CryptoKit
import Foundation

private let desktopAXObserverCallback: AXObserverCallback = { _, element, _, refcon in
    guard let refcon else { return }
    let service = Unmanaged<DesktopAccessibilityService>.fromOpaque(refcon).takeUnretainedValue()
    var pid: pid_t = 0
    if AXUIElementGetPid(element, &pid) == .success {
        service.markDirty(pid: pid)
    }
}

final class DesktopAccessibilityService {
    private struct Snapshot {
        let id: String
        let revision: Int
        let pid: pid_t
        let bundleIdentifier: String
        let applicationName: String
        let createdAtMs: Int
        let focusedNodeRef: String
        let stateHash: String
        let nodeHashes: [String: String]
        let nodePayloads: [String: [String: Any]]
        let elements: [String: AXUIElement]
        let maxNodes: Int
        let maxDepth: Int
    }

    private struct ElementRecord {
        let ref: String
        let parentRef: String
        let depth: Int
        let role: String
        let subrole: String
        let label: String
        let value: String
        let enabled: Bool
        let focused: Bool
        let selected: Bool
        let secure: Bool
        let actions: [String]
        let frame: CGRect?
        let children: [AXUIElement]
        let element: AXUIElement

        var modelPayload: [String: Any] {
            var payload: [String: Any] = [
                "nodeRef": ref,
                "parentRef": parentRef,
                "depth": depth,
                "role": role,
                "enabled": enabled,
                "focused": focused,
                "selected": selected,
                "secure": secure,
                "actions": actions,
            ]
            if !subrole.isEmpty { payload["subrole"] = subrole }
            if !label.isEmpty { payload["label"] = label }
            if !value.isEmpty && !secure { payload["value"] = value }
            return payload
        }

        var stateHash: String {
            let frameText = frame.map {
                "\(Int($0.origin.x.rounded())):\(Int($0.origin.y.rounded())):"
                    + "\(Int($0.width.rounded())):\(Int($0.height.rounded()))"
            } ?? ""
            return desktopSHA256(
                [
                    ref, parentRef, role, subrole, label, value,
                    enabled ? "1" : "0",
                    focused ? "1" : "0",
                    selected ? "1" : "0",
                    secure ? "1" : "0",
                    actions.joined(separator: ","),
                    frameText,
                ].joined(separator: "\u{1f}")
            )
        }
    }

    private struct TraversalResult {
        let records: [ElementRecord]
        let truncated: Bool
    }

    private let stateLock = NSLock()
    private var revisions: [pid_t: Int] = [:]
    private var observers: [pid_t: AXObserver] = [:]
    private var snapshots: [String: Snapshot] = [:]
    private var snapshotOrder: [String] = []
    private var latestSnapshotByPID: [pid_t: String] = [:]

    func handle(operation: String, request: [String: Any]) throws -> [String: Any] {
        switch operation {
        case "status":
            return status()
        case "list":
            return try listApplications(request)
        case "inspect":
            return try inspect(request)
        case "prepare_action":
            return try prepareAction(request)
        case "act":
            return try act(request)
        default:
            throw DesktopBridgeError.invalidRequest("unsupported_operation")
        }
    }

    func markDirty(pid: pid_t) {
        stateLock.lock()
        revisions[pid] = max(1, (revisions[pid] ?? 1) + 1)
        stateLock.unlock()
    }

    private func status() -> [String: Any] {
        let frontmost = NSWorkspace.shared.frontmostApplication
        return [
            "schemaVersion": "rag-ime.desktop-bridge-status.v1",
            "available": true,
            "accessibilityTrusted": AXIsProcessTrusted(),
            "secureInput": IsSecureEventInputEnabled(),
            "captureMode": "accessibility_semantics",
            "usesScreenCapture": false,
            "usesModelSuppliedCoordinates": false,
            "supportsTreeDiff": true,
            "supportsSemanticActions": true,
            "frontmostApplication": [
                "pid": Int(frontmost?.processIdentifier ?? 0),
                "bundleId": frontmost?.bundleIdentifier ?? "",
                "name": frontmost?.localizedName ?? "",
            ],
        ]
    }

    private func listApplications(_ request: [String: Any]) throws -> [String: Any] {
        guard AXIsProcessTrusted() else {
            throw DesktopBridgeError.permissionDenied("accessibility_not_trusted")
        }
        let includeBackground = request["includeBackground"] as? Bool ?? false
        let applications = NSWorkspace.shared.runningApplications
            .filter { application in
                !application.isTerminated
                    && application.processIdentifier != getpid()
                    && (includeBackground || application.activationPolicy == .regular)
            }
            .prefix(120)
        let deadline = Date().addingTimeInterval(0.8)
        var items: [[String: Any]] = []
        for application in applications {
            let bundleIdentifier = application.bundleIdentifier ?? ""
            let name = application.localizedName ?? ""
            let denied = DesktopPrivacyPolicy.denialReason(
                bundleIdentifier: bundleIdentifier,
                applicationName: name
            ) != nil
            var windows: [[String: Any]] = []
            if !denied, Date() < deadline {
                let appElement = AXUIElementCreateApplication(application.processIdentifier)
                _ = AXUIElementSetMessagingTimeout(appElement, 0.03)
                for window in copyElements(appElement, attribute: kAXWindowsAttribute as CFString).prefix(8) {
                    guard Date() < deadline else { break }
                    let role = copyString(window, attribute: kAXRoleAttribute as CFString)
                    let title = copyString(window, attribute: kAXTitleAttribute as CFString)
                    let privacyRestricted = DesktopPrivacyPolicy.denialReason(
                        bundleIdentifier: bundleIdentifier,
                        applicationName: name,
                        metadata: title
                    ) != nil
                    windows.append([
                        "role": role,
                        "title": privacyRestricted ? "" : String(title.prefix(240)),
                        "privacyRestricted": privacyRestricted,
                    ])
                }
            }
            items.append([
                "pid": Int(application.processIdentifier),
                "bundleId": bundleIdentifier,
                "name": name,
                "active": application.isActive,
                "hidden": application.isHidden,
                "terminated": application.isTerminated,
                "privacyRestricted": denied,
                "windows": windows,
            ])
        }
        items.sort {
            let left = $0["active"] as? Bool ?? false
            let right = $1["active"] as? Bool ?? false
            if left != right { return left }
            return String(describing: $0["name"] ?? "") < String(describing: $1["name"] ?? "")
        }
        return [
            "schemaVersion": "rag-ime.desktop-application-list.v1",
            "captureMode": "accessibility_semantics",
            "items": items,
            "count": items.count,
        ]
    }

    private func inspect(_ request: [String: Any]) throws -> [String: Any] {
        guard AXIsProcessTrusted() else {
            throw DesktopBridgeError.permissionDenied("accessibility_not_trusted")
        }
        let application = try resolveApplication(request)
        let bundleIdentifier = application.bundleIdentifier ?? ""
        let applicationName = application.localizedName ?? ""
        if let reason = DesktopPrivacyPolicy.denialReason(
            bundleIdentifier: bundleIdentifier,
            applicationName: applicationName
        ) {
            throw DesktopBridgeError.permissionDenied(reason)
        }
        let pid = application.processIdentifier
        installObserverIfNeeded(pid: pid)
        let initialRevision = currentRevision(pid: pid)
        let appElement = AXUIElementCreateApplication(pid)
        _ = AXUIElementSetMessagingTimeout(appElement, 0.08)
        let root = copyElement(appElement, attribute: kAXFocusedWindowAttribute as CFString)
            ?? copyElement(appElement, attribute: kAXMainWindowAttribute as CFString)
            ?? appElement
        let windowTitle = copyString(root, attribute: kAXTitleAttribute as CFString)
        if let reason = DesktopPrivacyPolicy.denialReason(
            bundleIdentifier: bundleIdentifier,
            applicationName: applicationName,
            metadata: windowTitle
        ) {
            throw DesktopBridgeError.permissionDenied(reason)
        }

        let maxNodes = boundedInteger(request["maxNodes"], default: 160, minimum: 1, maximum: 400)
        let maxDepth = boundedInteger(request["maxDepth"], default: 8, minimum: 1, maximum: 12)
        let query = boundedString(request["query"], maximum: 300).lowercased()
        let traversal = traverse(
            root: root,
            maxNodes: maxNodes,
            maxDepth: maxDepth,
            deadline: Date().addingTimeInterval(0.9)
        )
        let records = traversal.records
        guard initialRevision == currentRevision(pid: pid) else {
            throw DesktopBridgeError.stale("desktop_changed_during_inspect")
        }

        let nodeHashes = Dictionary(uniqueKeysWithValues: records.map { ($0.ref, $0.stateHash) })
        let stateHash = desktopSHA256(
            records.map { "\($0.ref):\($0.stateHash)" }.joined(separator: "\n")
        )
        var revision = initialRevision
        if let previous = latestSnapshot(pid: pid),
           previous.stateHash != stateHash,
           previous.revision == initialRevision {
            markDirty(pid: pid)
            revision = currentRevision(pid: pid)
        }
        let snapshotID = "axsnap_\(UUID().uuidString.lowercased())"
        let focusedRef = records.first(where: \.focused)?.ref ?? ""
        let createdAtMs = currentTimeMs()
        let payloads: [String: [String: Any]] = Dictionary(
            uniqueKeysWithValues: records.map { record in
            var payload = record.modelPayload
            if !query.isEmpty {
                let haystack = "\(record.role) \(record.subrole) \(record.label) \(record.value)".lowercased()
                payload["matchesQuery"] = haystack.contains(query)
            }
            return (record.ref, payload)
        })
        let snapshot = Snapshot(
            id: snapshotID,
            revision: revision,
            pid: pid,
            bundleIdentifier: bundleIdentifier,
            applicationName: applicationName,
            createdAtMs: createdAtMs,
            focusedNodeRef: focusedRef,
            stateHash: stateHash,
            nodeHashes: nodeHashes,
            nodePayloads: payloads,
            elements: Dictionary(uniqueKeysWithValues: records.map { ($0.ref, $0.element) }),
            maxNodes: maxNodes,
            maxDepth: maxDepth
        )
        let sinceID = boundedString(request["sinceSnapshotId"], maximum: 200)
        let previous = snapshots[sinceID]
        store(snapshot)
        let diff = snapshotDiff(previous: previous, current: snapshot)
        let responseRecords: [ElementRecord]
        if !query.isEmpty {
            responseRecords = records.filter {
                payloads[$0.ref]?["matchesQuery"] as? Bool == true || $0.focused
            }
        } else if diff["fullSnapshot"] as? Bool == false {
            let changed = Set(
                ((diff["added"] as? [String]) ?? [])
                    + ((diff["updated"] as? [String]) ?? [])
            )
            responseRecords = records.filter { changed.contains($0.ref) }
        } else {
            responseRecords = records
        }
        return [
            "schemaVersion": "rag-ime.desktop-snapshot.v1",
            "snapshotId": snapshotID,
            "revision": revision,
            "capturedAtMs": createdAtMs,
            "captureMode": "accessibility_semantics",
            "application": [
                "pid": Int(pid),
                "bundleId": bundleIdentifier,
                "name": applicationName,
                "active": application.isActive,
                "windowTitle": String(windowTitle.prefix(240)),
            ],
            "focusedNodeRef": focusedRef,
            "nodes": responseRecords.map { payloads[$0.ref] ?? $0.modelPayload },
            "nodeCount": records.count,
            "returnedNodeCount": responseRecords.count,
            "truncated": traversal.truncated,
            "diff": diff,
        ]
    }

    private func prepareAction(_ request: [String: Any]) throws -> [String: Any] {
        let snapshot = try validatedSnapshot(request)
        let nodeRef = boundedString(request["nodeRef"], maximum: 200)
        guard let node = snapshot.nodePayloads[nodeRef],
              snapshot.elements[nodeRef] != nil,
              let nodeStateHash = snapshot.nodeHashes[nodeRef] else {
            throw DesktopBridgeError.invalidRequest("node_not_found")
        }
        guard node["secure"] as? Bool != true else {
            throw DesktopBridgeError.permissionDenied("secure_element")
        }
        let action = boundedString(request["action"], maximum: 80).lowercased()
        let supported = [
            "press", "click", "double_click", "right_click", "long_press",
            "focus", "set_text", "type_text", "key", "increment", "decrement",
            "show_menu", "scroll",
        ]
        guard supported.contains(action) else {
            throw DesktopBridgeError.invalidRequest("unsupported_action")
        }
        var actionPayload: [String: Any] = [
            "snapshotId": snapshot.id,
            "revision": snapshot.revision,
            "pid": Int(snapshot.pid),
            "bundleId": snapshot.bundleIdentifier,
            "nodeRef": nodeRef,
            "action": action,
        ]
        if action == "set_text" || action == "type_text" {
            guard let rawText = request["text"] as? String else {
                throw DesktopBridgeError.invalidRequest("text_is_required")
            }
            actionPayload["text"] = String(rawText.prefix(8_000))
            actionPayload["textChars"] = min(rawText.count, 8_000)
        }
        if action == "key" {
            let key = boundedString(request["key"], maximum: 40).lowercased()
            guard desktopKeyCode(key) != nil else {
                throw DesktopBridgeError.invalidRequest("unsupported_key")
            }
            actionPayload["key"] = key
            actionPayload["modifiers"] = normalizedModifiers(request["modifiers"])
        }
        if action == "long_press" {
            actionPayload["durationMs"] = boundedInteger(
                request["durationMs"],
                default: 650,
                minimum: 100,
                maximum: 3_000
            )
        }
        if action == "scroll" {
            let delta = boundedInteger(
                request["scrollDelta"],
                default: 3,
                minimum: -20,
                maximum: 20
            )
            guard delta != 0 else {
                throw DesktopBridgeError.invalidRequest("scroll_delta_must_not_be_zero")
            }
            actionPayload["scrollDelta"] = delta
        }
        let label = boundedString(node["label"], maximum: 120)
        let baseState: [String: Any] = [
            "snapshotId": snapshot.id,
            "revision": snapshot.revision,
            "nodeStateSha256": nodeStateHash,
            "applicationStateSha256": snapshot.stateHash,
            "capturedAtMs": snapshot.createdAtMs,
        ]
        return [
            "schemaVersion": "rag-ime.desktop-action-preview.v1",
            "summary": "在 \(snapshot.applicationName) 的 \(label.isEmpty ? String(describing: node["role"] ?? "控件") : label) 执行 \(action)",
            "actionPayload": actionPayload,
            "baseState": baseState,
            "requiresApproval": true,
        ]
    }

    private func act(_ request: [String: Any]) throws -> [String: Any] {
        guard AXIsProcessTrusted() else {
            throw DesktopBridgeError.permissionDenied("accessibility_not_trusted")
        }
        guard let actionPayload = request["actionPayload"] as? [String: Any],
              let baseState = request["baseState"] as? [String: Any] else {
            throw DesktopBridgeError.invalidRequest("actionPayload_and_baseState_are_required")
        }
        let snapshot = try validatedSnapshot(actionPayload)
        let nodeRef = boundedString(actionPayload["nodeRef"], maximum: 200)
        guard baseState["snapshotId"] as? String == snapshot.id,
              boundedInteger(
                  baseState["revision"],
                  default: -1,
                  minimum: -1,
                  maximum: Int.max
              ) == snapshot.revision,
              let expectedNodeHash = baseState["nodeStateSha256"] as? String,
              expectedNodeHash == snapshot.nodeHashes[nodeRef],
              baseState["applicationStateSha256"] as? String == snapshot.stateHash else {
            throw DesktopBridgeError.stale("desktop_node_changed_after_preview")
        }
        let refreshed = try refreshSnapshotForAction(
            snapshot,
            nodeRef: nodeRef,
            expectedNodeHash: expectedNodeHash
        )
        guard let element = refreshed.elements[nodeRef] else {
            throw DesktopBridgeError.stale("desktop_node_changed_after_preview")
        }
        let action = boundedString(actionPayload["action"], maximum: 80).lowercased()
        let method = try perform(
            action: action,
            payload: actionPayload,
            element: element,
            pid: refreshed.pid,
            nodePayload: refreshed.nodePayloads[nodeRef] ?? [:]
        )
        markDirty(pid: refreshed.pid)
        Thread.sleep(forTimeInterval: 0.06)
        let postSnapshot = try inspect([
            "pid": Int(refreshed.pid),
            "maxNodes": refreshed.maxNodes,
            "maxDepth": refreshed.maxDepth,
            "sinceSnapshotId": refreshed.id,
        ])
        return [
            "schemaVersion": "rag-ime.desktop-action-receipt.v1",
            "applied": true,
            "action": action,
            "nodeRef": nodeRef,
            "method": method,
            "previousSnapshotId": snapshot.id,
            "postSnapshot": postSnapshot,
        ]
    }

    private func refreshSnapshotForAction(
        _ snapshot: Snapshot,
        nodeRef: String,
        expectedNodeHash: String
    ) throws -> Snapshot {
        let result = try inspect([
            "pid": Int(snapshot.pid),
            "maxNodes": snapshot.maxNodes,
            "maxDepth": snapshot.maxDepth,
            "sinceSnapshotId": snapshot.id,
        ])
        let refreshedID = boundedString(result["snapshotId"], maximum: 200)
        guard let refreshed = snapshots[refreshedID],
              refreshed.pid == snapshot.pid,
              refreshed.revision == snapshot.revision,
              refreshed.stateHash == snapshot.stateHash,
              refreshed.nodeHashes[nodeRef] == expectedNodeHash else {
            throw DesktopBridgeError.stale("desktop_changed_after_approval")
        }
        return refreshed
    }

    private func perform(
        action: String,
        payload: [String: Any],
        element: AXUIElement,
        pid: pid_t,
        nodePayload: [String: Any]
    ) throws -> String {
        let application = NSRunningApplication(processIdentifier: pid)
        _ = application?.activate(options: [.activateIgnoringOtherApps])
        _ = AXUIElementSetMessagingTimeout(element, 0.12)
        switch action {
        case "press":
            try requireAXSuccess(AXUIElementPerformAction(element, kAXPressAction as CFString))
            return "ax_press"
        case "show_menu":
            try requireAXSuccess(AXUIElementPerformAction(element, kAXShowMenuAction as CFString))
            return "ax_show_menu"
        case "increment":
            try requireAXSuccess(AXUIElementPerformAction(element, kAXIncrementAction as CFString))
            return "ax_increment"
        case "decrement":
            try requireAXSuccess(AXUIElementPerformAction(element, kAXDecrementAction as CFString))
            return "ax_decrement"
        case "focus":
            try requireAXSuccess(
                AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            )
            return "ax_focus"
        case "set_text":
            guard nodePayload["secure"] as? Bool != true else {
                throw DesktopBridgeError.permissionDenied("secure_element")
            }
            let text = payload["text"] as? String ?? ""
            try requireAXSuccess(
                AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString, text as CFString)
            )
            return "ax_set_value"
        case "type_text":
            guard nodePayload["secure"] as? Bool != true else {
                throw DesktopBridgeError.permissionDenied("secure_element")
            }
            _ = AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            let text = payload["text"] as? String ?? ""
            let selectedResult = AXUIElementSetAttributeValue(
                element,
                kAXSelectedTextAttribute as CFString,
                text as CFString
            )
            if selectedResult == .success { return "ax_selected_text" }
            try postUnicodeText(text)
            return "cg_unicode_keyboard"
        case "key":
            let key = boundedString(payload["key"], maximum: 40).lowercased()
            guard let keyCode = desktopKeyCode(key) else {
                throw DesktopBridgeError.invalidRequest("unsupported_key")
            }
            _ = AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
            try postKey(keyCode, modifiers: normalizedModifiers(payload["modifiers"]))
            return "cg_keyboard"
        case "scroll":
            let point = try validatedActionPoint(element)
            let delta = boundedInteger(payload["scrollDelta"], default: 3, minimum: -20, maximum: 20)
            try postScroll(delta: delta, at: point)
            return "cg_scroll_at_ax_bounds"
        case "click", "double_click", "right_click", "long_press":
            if action == "click",
               AXUIElementPerformAction(element, kAXPressAction as CFString) == .success {
                return "ax_press"
            }
            let point = try validatedActionPoint(element)
            try postMouseAction(
                action,
                at: point,
                durationMs: boundedInteger(
                    payload["durationMs"],
                    default: 650,
                    minimum: 100,
                    maximum: 3_000
                )
            )
            return "cg_mouse_at_ax_bounds"
        default:
            throw DesktopBridgeError.invalidRequest("unsupported_action")
        }
    }

    private func validatedSnapshot(_ request: [String: Any]) throws -> Snapshot {
        let snapshotID = boundedString(request["snapshotId"], maximum: 200)
        let revision = boundedInteger(request["revision"], default: -1, minimum: -1, maximum: Int.max)
        guard let snapshot = snapshots[snapshotID] else {
            throw DesktopBridgeError.stale("snapshot_not_found")
        }
        guard revision == snapshot.revision,
              currentRevision(pid: snapshot.pid) == snapshot.revision else {
            throw DesktopBridgeError.stale("desktop_changed_after_snapshot")
        }
        guard NSRunningApplication(processIdentifier: snapshot.pid)?.isTerminated == false else {
            throw DesktopBridgeError.stale("application_terminated")
        }
        return snapshot
    }

    private func resolveApplication(_ request: [String: Any]) throws -> NSRunningApplication {
        let requestedPID = boundedInteger(request["pid"], default: 0, minimum: 0, maximum: Int(Int32.max))
        if requestedPID > 0,
           let application = NSRunningApplication(processIdentifier: pid_t(requestedPID)),
           !application.isTerminated {
            return application
        }
        let bundleIdentifier = boundedString(request["bundleId"], maximum: 300)
        if !bundleIdentifier.isEmpty,
           let application = NSRunningApplication.runningApplications(
               withBundleIdentifier: bundleIdentifier
           ).first(where: { !$0.isTerminated }) {
            return application
        }
        if let frontmost = NSWorkspace.shared.frontmostApplication,
           frontmost.processIdentifier != getpid(),
           !frontmost.isTerminated {
            return frontmost
        }
        throw DesktopBridgeError.unavailable("target_application_not_found")
    }

    private func traverse(
        root: AXUIElement,
        maxNodes: Int,
        maxDepth: Int,
        deadline: Date
    ) -> TraversalResult {
        var queue: [(AXUIElement, String, Int, Int)] = [(root, "", 0, 0)]
        var queueIndex = 0
        var records: [ElementRecord] = []
        var visited = Set<CFHashCode>()
        while queueIndex < queue.count, records.count < maxNodes, Date() < deadline {
            let (element, parentRef, depth, siblingIndex) = queue[queueIndex]
            queueIndex += 1
            let identity = CFHash(element)
            guard !visited.contains(identity) else { continue }
            visited.insert(identity)
            _ = AXUIElementSetMessagingTimeout(element, 0.05)
            let attributes = copySemanticAttributes(element)
            let role = stringValue(attributes[kAXRoleAttribute as String])
            let subrole = stringValue(attributes[kAXSubroleAttribute as String])
            let title = stringValue(attributes[kAXTitleAttribute as String])
            let description = stringValue(attributes[kAXDescriptionAttribute as String])
            let placeholder = stringValue(attributes[kAXPlaceholderValueAttribute as String])
            let help = stringValue(attributes[kAXHelpAttribute as String])
            let identifier = stringValue(attributes[kAXIdentifierAttribute as String])
            let label = firstNonempty(title, description, placeholder, help)
            let metadata = [title, description, placeholder, help, identifier].joined(separator: " ")
            let secure = DesktopPrivacyPolicy.elementIsSecure(
                role: role,
                subrole: subrole,
                metadata: metadata
            )
            let frame = frameValue(
                position: attributes[kAXPositionAttribute as String],
                size: attributes[kAXSizeAttribute as String]
            )
            let fingerprintBasis = !identifier.isEmpty
                ? "id:\(parentRef)|\(identifier)|\(role)|\(siblingIndex)"
                : "\(parentRef)|\(role)|\(subrole)|\(label)|\(siblingIndex)"
            let nodeRef = "ax_\(desktopSHA256(fingerprintBasis).prefix(20))"
            let rawValue = secure ? "" : semanticStringValue(attributes[kAXValueAttribute as String])
            let value = String(rawValue.prefix(800))
            let children = secure || depth >= maxDepth
                ? []
                : semanticChildren(attributes)
            let record = ElementRecord(
                ref: nodeRef,
                parentRef: parentRef,
                depth: depth,
                role: role,
                subrole: subrole,
                label: String(label.prefix(240)),
                value: value,
                enabled: boolValue(attributes[kAXEnabledAttribute as String], default: true),
                focused: boolValue(attributes[kAXFocusedAttribute as String], default: false),
                selected: boolValue(attributes[kAXSelectedAttribute as String], default: false),
                secure: secure,
                actions: copyActions(element),
                frame: frame,
                children: children,
                element: element
            )
            records.append(record)
            for (index, child) in children.enumerated() {
                queue.append((child, nodeRef, depth + 1, index))
            }
        }
        return TraversalResult(records: records, truncated: queueIndex < queue.count)
    }

    private func copySemanticAttributes(_ element: AXUIElement) -> [String: Any] {
        let names: [CFString] = [
            kAXRoleAttribute as CFString,
            kAXSubroleAttribute as CFString,
            kAXTitleAttribute as CFString,
            kAXDescriptionAttribute as CFString,
            kAXPlaceholderValueAttribute as CFString,
            kAXHelpAttribute as CFString,
            kAXIdentifierAttribute as CFString,
            kAXValueAttribute as CFString,
            kAXEnabledAttribute as CFString,
            kAXFocusedAttribute as CFString,
            kAXSelectedAttribute as CFString,
            kAXPositionAttribute as CFString,
            kAXSizeAttribute as CFString,
            kAXChildrenAttribute as CFString,
            kAXVisibleChildrenAttribute as CFString,
            "AXChildrenInNavigationOrder" as CFString,
            kAXContentsAttribute as CFString,
        ]
        var copied: CFArray?
        let error = AXUIElementCopyMultipleAttributeValues(element, names as CFArray, [], &copied)
        guard error == .success, let values = copied as? [Any], values.count == names.count else {
            return Dictionary(uniqueKeysWithValues: names.map { name in
                (name as String, copyAttribute(element, attribute: name) ?? NSNull())
            })
        }
        return Dictionary(uniqueKeysWithValues: zip(names, values).map { name, value in
            (name as String, value)
        })
    }

    private func semanticChildren(_ attributes: [String: Any]) -> [AXUIElement] {
        let childAttributes = [
            kAXChildrenAttribute as String,
            kAXVisibleChildrenAttribute as String,
            "AXChildrenInNavigationOrder",
            kAXContentsAttribute as String,
        ]
        var children: [AXUIElement] = []
        var seen = Set<CFHashCode>()
        for attribute in childAttributes {
            for child in elementArrayValue(attributes[attribute]) {
                let identity = CFHash(child)
                guard !seen.contains(identity) else { continue }
                seen.insert(identity)
                children.append(child)
            }
        }
        return children
    }

    private func copyActions(_ element: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success,
              let values = names as? [String] else { return [] }
        let mapped: [String] = values.map { action in
            switch action {
            case kAXPressAction: return "press"
            case kAXShowMenuAction: return "show_menu"
            case kAXIncrementAction: return "increment"
            case kAXDecrementAction: return "decrement"
            case kAXConfirmAction: return "confirm"
            case kAXCancelAction: return "cancel"
            default: return action
            }
        }
        return Array(mapped.prefix(20))
    }

    private func snapshotDiff(previous: Snapshot?, current: Snapshot) -> [String: Any] {
        guard let previous, previous.pid == current.pid else {
            return [
                "baseSnapshotId": "",
                "fullSnapshot": true,
                "added": [],
                "addedCount": current.nodeHashes.count,
                "updated": [],
                "removed": [],
                "focusChanged": !current.focusedNodeRef.isEmpty,
            ]
        }
        let previousKeys = Set(previous.nodeHashes.keys)
        let currentKeys = Set(current.nodeHashes.keys)
        return [
            "baseSnapshotId": previous.id,
            "fullSnapshot": false,
            "added": Array(currentKeys.subtracting(previousKeys)).sorted(),
            "updated": Array(currentKeys.intersection(previousKeys))
                .filter { previous.nodeHashes[$0] != current.nodeHashes[$0] }
                .sorted(),
            "removed": Array(previousKeys.subtracting(currentKeys)).sorted(),
            "focusChanged": previous.focusedNodeRef != current.focusedNodeRef,
        ]
    }

    private func store(_ snapshot: Snapshot) {
        snapshots[snapshot.id] = snapshot
        snapshotOrder.append(snapshot.id)
        latestSnapshotByPID[snapshot.pid] = snapshot.id
        while snapshotOrder.count > 8 {
            let removedID = snapshotOrder.removeFirst()
            if let removed = snapshots.removeValue(forKey: removedID),
               latestSnapshotByPID[removed.pid] == removedID {
                latestSnapshotByPID.removeValue(forKey: removed.pid)
            }
        }
    }

    private func latestSnapshot(pid: pid_t) -> Snapshot? {
        guard let id = latestSnapshotByPID[pid] else { return nil }
        return snapshots[id]
    }

    private func currentRevision(pid: pid_t) -> Int {
        stateLock.lock()
        defer { stateLock.unlock() }
        let value = max(1, revisions[pid] ?? 1)
        revisions[pid] = value
        return value
    }

    private func installObserverIfNeeded(pid: pid_t) {
        stateLock.lock()
        if observers[pid] != nil {
            stateLock.unlock()
            return
        }
        stateLock.unlock()
        var observer: AXObserver?
        guard AXObserverCreate(pid, desktopAXObserverCallback, &observer) == .success,
              let observer else { return }
        let app = AXUIElementCreateApplication(pid)
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        for notification in [
            kAXFocusedWindowChangedNotification,
            kAXFocusedUIElementChangedNotification,
            kAXWindowCreatedNotification,
            kAXUIElementDestroyedNotification,
            kAXValueChangedNotification,
            kAXSelectedChildrenChangedNotification,
        ] {
            _ = AXObserverAddNotification(observer, app, notification as CFString, refcon)
        }
        CFRunLoopAddSource(CFRunLoopGetMain(), AXObserverGetRunLoopSource(observer), .commonModes)
        stateLock.lock()
        observers[pid] = observer
        stateLock.unlock()
    }
}

private func copyAttribute(_ element: AXUIElement, attribute: CFString) -> Any? {
    var value: AnyObject?
    guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else {
        return nil
    }
    return value
}

private func copyElement(_ element: AXUIElement, attribute: CFString) -> AXUIElement? {
    guard let value = copyAttribute(element, attribute: attribute) else { return nil }
    let object = value as CFTypeRef
    guard CFGetTypeID(object) == AXUIElementGetTypeID() else { return nil }
    return unsafeBitCast(object, to: AXUIElement.self)
}

private func copyElements(_ element: AXUIElement, attribute: CFString) -> [AXUIElement] {
    guard let values = copyAttribute(element, attribute: attribute) as? [Any] else { return [] }
    return elementArrayValue(values)
}

private func copyString(_ element: AXUIElement, attribute: CFString) -> String {
    stringValue(copyAttribute(element, attribute: attribute))
}

private func elementArrayValue(_ value: Any?) -> [AXUIElement] {
    guard let values = value as? [Any] else { return [] }
    return values.compactMap { item in
        let object = item as CFTypeRef
        guard CFGetTypeID(object) == AXUIElementGetTypeID() else { return nil }
        return unsafeBitCast(object, to: AXUIElement.self)
    }
}

private func stringValue(_ value: Any?) -> String {
    if let text = value as? String { return text.trimmingCharacters(in: .whitespacesAndNewlines) }
    if let text = value as? NSAttributedString {
        return text.string.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return ""
}

private func semanticStringValue(_ value: Any?) -> String {
    if let text = value as? String { return text.trimmingCharacters(in: .whitespacesAndNewlines) }
    if let number = value as? NSNumber { return number.stringValue }
    if let attributed = value as? NSAttributedString {
        return attributed.string.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return ""
}

private func boolValue(_ value: Any?, default defaultValue: Bool) -> Bool {
    (value as? NSNumber)?.boolValue ?? defaultValue
}

private func frameValue(position: Any?, size: Any?) -> CGRect? {
    guard let position, let size else { return nil }
    let positionObject = position as CFTypeRef
    let sizeObject = size as CFTypeRef
    guard CFGetTypeID(positionObject) == AXValueGetTypeID(),
          CFGetTypeID(sizeObject) == AXValueGetTypeID() else { return nil }
    let positionValue = unsafeBitCast(positionObject, to: AXValue.self)
    let sizeValue = unsafeBitCast(sizeObject, to: AXValue.self)
    var point = CGPoint.zero
    var dimensions = CGSize.zero
    guard AXValueGetValue(positionValue, .cgPoint, &point),
          AXValueGetValue(sizeValue, .cgSize, &dimensions),
          dimensions.width > 0,
          dimensions.height > 0 else { return nil }
    return CGRect(origin: point, size: dimensions)
}

private func elementFrame(_ element: AXUIElement) throws -> CGRect {
    guard let frame = frameValue(
        position: copyAttribute(element, attribute: kAXPositionAttribute as CFString),
        size: copyAttribute(element, attribute: kAXSizeAttribute as CFString)
    ) else {
        throw DesktopBridgeError.actionFailed("element_bounds_unavailable")
    }
    return frame
}

private func validatedActionPoint(_ element: AXUIElement) throws -> CGPoint {
    let frame = try elementFrame(element)
    let point = CGPoint(x: frame.midX, y: frame.midY)
    let systemWide = AXUIElementCreateSystemWide()
    _ = AXUIElementSetMessagingTimeout(systemWide, 0.08)
    var hitElement: AXUIElement?
    guard AXUIElementCopyElementAtPosition(
        systemWide,
        Float(point.x),
        Float(point.y),
        &hitElement
    ) == .success,
          let hitElement,
          isElement(hitElement, sameAsOrDescendantOf: element) else {
        throw DesktopBridgeError.stale("ax_bounds_hit_test_changed")
    }
    return point
}

private func isElement(_ candidate: AXUIElement, sameAsOrDescendantOf target: AXUIElement) -> Bool {
    var current: AXUIElement? = candidate
    for _ in 0..<12 {
        guard let element = current else { return false }
        if CFEqual(element, target) { return true }
        current = copyElement(element, attribute: kAXParentAttribute as CFString)
    }
    return false
}

private func firstNonempty(_ values: String...) -> String {
    values.first(where: { !$0.isEmpty }) ?? ""
}

private func boundedInteger(
    _ value: Any?,
    default defaultValue: Int,
    minimum: Int,
    maximum: Int
) -> Int {
    let parsed: Int
    if let number = value as? NSNumber {
        parsed = number.intValue
    } else if let text = value as? String, let number = Int(text) {
        parsed = number
    } else {
        parsed = defaultValue
    }
    return max(minimum, min(maximum, parsed))
}

private func normalizedModifiers(_ value: Any?) -> [String] {
    let allowed = ["command", "option", "control", "shift", "fn"]
    guard let values = value as? [Any] else { return [] }
    var result: [String] = []
    for item in values {
        let modifier = String(describing: item).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if allowed.contains(modifier), !result.contains(modifier) {
            result.append(modifier)
        }
    }
    return result
}

private func desktopKeyCode(_ key: String) -> CGKeyCode? {
    let codes: [String: Int] = [
        "return": kVK_Return,
        "enter": kVK_ANSI_KeypadEnter,
        "tab": kVK_Tab,
        "escape": kVK_Escape,
        "space": kVK_Space,
        "delete": kVK_Delete,
        "forward_delete": kVK_ForwardDelete,
        "left": kVK_LeftArrow,
        "right": kVK_RightArrow,
        "up": kVK_UpArrow,
        "down": kVK_DownArrow,
        "home": kVK_Home,
        "end": kVK_End,
        "page_up": kVK_PageUp,
        "page_down": kVK_PageDown,
    ]
    return codes[key].map(CGKeyCode.init)
}

private func eventFlags(_ modifiers: [String]) -> CGEventFlags {
    var flags: CGEventFlags = []
    if modifiers.contains("command") { flags.insert(.maskCommand) }
    if modifiers.contains("option") { flags.insert(.maskAlternate) }
    if modifiers.contains("control") { flags.insert(.maskControl) }
    if modifiers.contains("shift") { flags.insert(.maskShift) }
    if modifiers.contains("fn") { flags.insert(.maskSecondaryFn) }
    return flags
}

private func postKey(_ keyCode: CGKeyCode, modifiers: [String]) throws {
    guard let source = CGEventSource(stateID: .hidSystemState),
          let down = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: keyCode, keyDown: false) else {
        throw DesktopBridgeError.actionFailed("keyboard_event_creation_failed")
    }
    let flags = eventFlags(modifiers)
    down.flags = flags
    up.flags = flags
    down.post(tap: .cghidEventTap)
    up.post(tap: .cghidEventTap)
}

private func postUnicodeText(_ text: String) throws {
    guard !text.isEmpty else { return }
    guard let source = CGEventSource(stateID: .hidSystemState),
          let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else {
        throw DesktopBridgeError.actionFailed("unicode_event_creation_failed")
    }
    let utf16 = Array(text.utf16.prefix(8_000))
    utf16.withUnsafeBufferPointer { buffer in
        down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress)
        up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress)
    }
    down.post(tap: .cghidEventTap)
    up.post(tap: .cghidEventTap)
}

private func postMouseAction(_ action: String, at point: CGPoint, durationMs: Int) throws {
    guard let source = CGEventSource(stateID: .hidSystemState) else {
        throw DesktopBridgeError.actionFailed("mouse_event_source_unavailable")
    }
    let button: CGMouseButton = action == "right_click" ? .right : .left
    let downType: CGEventType = action == "right_click" ? .rightMouseDown : .leftMouseDown
    let upType: CGEventType = action == "right_click" ? .rightMouseUp : .leftMouseUp
    func click(count: Int) throws {
        guard let down = CGEvent(mouseEventSource: source, mouseType: downType, mouseCursorPosition: point, mouseButton: button),
              let up = CGEvent(mouseEventSource: source, mouseType: upType, mouseCursorPosition: point, mouseButton: button) else {
            throw DesktopBridgeError.actionFailed("mouse_event_creation_failed")
        }
        down.setIntegerValueField(.mouseEventClickState, value: Int64(count))
        up.setIntegerValueField(.mouseEventClickState, value: Int64(count))
        down.post(tap: .cghidEventTap)
        if action == "long_press" {
            usleep(useconds_t(durationMs * 1_000))
        }
        up.post(tap: .cghidEventTap)
    }
    try click(count: 1)
    if action == "double_click" {
        usleep(60_000)
        try click(count: 2)
    }
}

private func postScroll(delta: Int, at point: CGPoint) throws {
    guard let source = CGEventSource(stateID: .hidSystemState),
          let event = CGEvent(
              scrollWheelEvent2Source: source,
              units: .line,
              wheelCount: 1,
              wheel1: Int32(delta),
              wheel2: 0,
              wheel3: 0
          ) else {
        throw DesktopBridgeError.actionFailed("scroll_event_creation_failed")
    }
    event.location = point
    event.post(tap: .cghidEventTap)
}

private func requireAXSuccess(_ result: AXError) throws {
    guard result == .success else {
        throw DesktopBridgeError.actionFailed("accessibility_action_failed_\(result.rawValue)")
    }
}

private func desktopSHA256(_ value: String) -> String {
    SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
}

private func currentTimeMs() -> Int {
    Int(Date().timeIntervalSince1970 * 1_000)
}
