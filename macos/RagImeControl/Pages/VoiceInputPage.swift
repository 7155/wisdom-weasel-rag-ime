import AppKit
import SwiftUI

struct VoiceInputPage: View {
    @State private var provider = VoiceASRProvider.nativeStreaming
    @State private var appID = ""
    @State private var accessToken = ""
    @State private var resourceID = VoiceKeychainStore.defaultResourceID
    @State private var endpoint = VoiceKeychainStore.defaultRealtimeEndpoint
    @State private var modelName = VoiceKeychainStore.defaultRealtimeModel
    @State private var tokenConfigured = false
    @State private var saveMessage = ""
    @State private var hotwordsEnabled = false
    @State private var hotwordsText = ""
    @State private var savedHotwordCount = 0
    @State private var hotwordMessage = ""
    @State private var agentRunning = false
    @State private var voiceAgentStatus: VoiceAgentStatus?
    @State private var hotkeyChoice = VoiceHotkeyChoice.middleMouse

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "语音输入", subtitle: "按住鼠标滚轮中键立即听写，松开后由流式语音服务原位定稿")
                Spacer()
            }
            .padding(.horizontal, 30)
            .padding(.vertical, 22)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    pushToTalkSurface
                    HStack(alignment: .top, spacing: 42) {
                        statusSection.frame(maxWidth: .infinity, alignment: .topLeading)
                        credentialSection.frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                    if let telemetry = voiceAgentStatus?.telemetry {
                        Divider()
                        telemetrySection(telemetry)
                    }
                    if provider.supportsHotwords {
                        Divider()
                        hotwordSection
                    }
                    Divider()
                    behaviorSection
                }
                .padding(.horizontal, 32)
                .padding(.vertical, 28)
                .frame(maxWidth: 1080, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .task {
            load()
            while !Task.isCancelled {
                refreshAgentState()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private var pushToTalkSurface: some View {
        HStack(spacing: 18) {
            Image(systemName: agentRunning ? "waveform.circle.fill" : "waveform.circle")
                .font(.system(size: 42, weight: .medium))
                .foregroundStyle(agentRunning ? Color.green : Color.accentColor)
            VStack(alignment: .leading, spacing: 5) {
                Text(agentRunning ? "语音代理已待命" : "启动后即可在任意文本框听写")
                    .font(.title3.weight(.semibold))
                Text("默认按住滚轮中键说话，松开即完成。Esc 取消本次转写。")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(hotkeyChoice.compactTitle)
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Color(nsColor: .windowBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))
            Button(agentRunning ? "停止" : "启动") { toggleAgent() }
                .buttonStyle(.borderedProminent)
                .disabled(!credentialsReady)
        }
        .padding(20)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor).opacity(0.65), lineWidth: 0.7))
    }

    private func telemetrySection(_ telemetry: VoiceSessionTelemetry) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("最近一次流式会话").font(.headline)
            LabeledContent("网络") { Text(networkLabel(telemetry.networkState)) }
            LabeledContent("首个 Partial") { Text(latencyLabel(telemetry.firstPartialLatencyMs)) }
            LabeledContent("松开至 Final") { Text(latencyLabel(telemetry.finalLatencyMs)) }
            LabeledContent("音频帧") { Text("\(telemetry.pcmFrameCount)") }
            LabeledContent("丢弃帧") {
                Text("\(telemetry.droppedPCMFrameCount)")
                    .foregroundStyle(telemetry.droppedPCMFrameCount == 0 ? Color.secondary : Color.orange)
            }
            LabeledContent("转写修订") { Text("\(telemetry.partialRevisionCount)") }
            Text("仅记录状态、数量与时延，不保存音频或转写文本。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var statusSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("运行状态").font(.headline)
            voiceStatusRow("语音代理", ok: agentRunning, detail: agentRunning ? "后台运行中" : "尚未启动")
            voiceStatusRow("中键监听", ok: voiceAgentStatus?.hotkeyInstalled == true, detail: hotkeyMonitorStatus)
            voiceStatusRow("辅助功能", ok: voiceAgentStatus?.accessibilityTrusted == true, detail: accessibilityStatus)
            voiceStatusRow("麦克风", ok: voiceAgentStatus?.microphoneAuthorization == "authorized", detail: microphoneStatus)
            voiceStatusRow("语音服务凭据", ok: credentialsReady, detail: tokenConfigured ? "已按服务隔离保存，启动时不再询问密码" : "尚未配置")
            voiceStatusRow(
                "请求级热词",
                ok: voiceAgentStatus?.hotwordsEnabled == true,
                detail: hotwordStatus,
                neutral: voiceAgentStatus?.hotwordsEnabled != true && !hotwordsEnabled
            )
            HStack {
                if voiceAgentStatus?.accessibilityTrusted != true {
                    Button("辅助功能设置", systemImage: "hand.raised") {
                        openPrivacyPane("Privacy_Accessibility")
                    }
                }
                if voiceAgentStatus?.microphoneAuthorization != "authorized" {
                    Button("麦克风设置", systemImage: "mic") {
                        openPrivacyPane("Privacy_Microphone")
                    }
                }
                Button(agentRunning ? "停止语音代理" : "启动语音代理", systemImage: agentRunning ? "stop.fill" : "play.fill") {
                    toggleAgent()
                }
                .disabled(!credentialsReady)
            }
        }
    }

    private var credentialSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("流式语音识别").font(.headline)
            LabeledContent("服务") {
                Picker("服务", selection: $provider) {
                    ForEach(VoiceASRProvider.allCases) { item in
                        Text(item.title).tag(item)
                    }
                }
                .labelsHidden()
                .frame(width: 330)
                .onChange(of: provider) { value in loadProvider(value) }
            }
            LabeledContent("Access Token") {
                SecureField(tokenConfigured ? "已配置，留空则保持不变" : "Access Token", text: $accessToken)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 330)
            }
            if provider == .nativeStreaming {
                LabeledContent("App ID") {
                    TextField("App ID", text: $appID).textFieldStyle(.roundedBorder).frame(width: 330)
                }
                LabeledContent("Resource ID") {
                    TextField("Resource ID", text: $resourceID).textFieldStyle(.roundedBorder).frame(width: 330)
                }
            } else {
                LabeledContent("WebSocket") {
                    TextField("wss://...", text: $endpoint).textFieldStyle(.roundedBorder).frame(width: 330)
                }
                LabeledContent("转写模型") {
                    TextField("transcription model", text: $modelName).textFieldStyle(.roundedBorder).frame(width: 330)
                }
                Text("兼容 input_audio_buffer.append/commit 与 transcription delta/completed 事件。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("保存到本机", systemImage: "key.fill") { save() }
                    .buttonStyle(.borderedProminent)
                if !saveMessage.isEmpty {
                    Text(saveMessage).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private var behaviorSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("使用").font(.headline)
            LabeledContent("按住说话") {
                Picker("按住说话", selection: $hotkeyChoice) {
                    ForEach(VoiceHotkeyChoice.allCases) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .labelsHidden()
                .frame(width: 220)
                .onChange(of: hotkeyChoice) { value in saveHotkey(value) }
            }
            LabeledContent("松开") { Text("发送终帧并原位定稿") }
            LabeledContent("Esc") { Text("取消并移除本次临时转写") }
            LabeledContent("隐私") { Text("密码、账号与 Secure Input 输入框不启动录音，也不写入历史") }
        }
    }

    private var hotwordSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("请求级热词").font(.headline)
                Spacer()
                Toggle("启用", isOn: $hotwordsEnabled)
                    .toggleStyle(.switch)
                    .labelsHidden()
                    .help("启用请求级语音热词")
            }
            LabeledContent("热词") {
                TextEditor(text: $hotwordsText)
                    .font(.system(.body, design: .monospaced))
                    .scrollContentBackground(.hidden)
                    .padding(6)
                    .frame(width: 560, height: 112)
                    .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
                    )
            }
            LabeledContent("边界") {
                Text("最多 32 条 · 每条 2–9 字 · 仅中英文字母")
                    .foregroundStyle(.secondary)
            }
            LabeledContent("数据源") {
                Text("仅发送此处显式保存的词，不读取 Rime 用户词典")
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("保存热词", systemImage: "text.badge.checkmark") { saveHotwords() }
                    .buttonStyle(.borderedProminent)
                Button("清空", systemImage: "trash") { clearHotwords() }
                    .disabled(hotwordsText.isEmpty && !hotwordsEnabled)
                if !hotwordMessage.isEmpty {
                    Text(hotwordMessage).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func voiceStatusRow(_ title: String, ok: Bool, detail: String, neutral: Bool = false) -> some View {
        HStack(spacing: 10) {
            Image(systemName: neutral ? "minus.circle.fill" : (ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill"))
                .foregroundStyle(neutral ? Color.secondary : (ok ? Color.green : Color.orange))
            Text(title).frame(width: 100, alignment: .leading)
            Text(detail).foregroundStyle(.secondary)
            Spacer()
        }
    }

    private var microphoneStatus: String {
        guard agentRunning else { return "启动语音代理后检查" }
        switch voiceAgentStatus?.microphoneAuthorization {
        case "authorized": return "语音代理已授权"
        case "not_determined": return "首次按快捷键时由语音代理请求"
        case "denied", "restricted": return "语音代理未获授权"
        case .none: return "等待语音代理回报"
        default: return "状态未知"
        }
    }

    private var accessibilityStatus: String {
        guard agentRunning else { return "启动语音代理后检查" }
        guard let voiceAgentStatus else { return "等待语音代理回报" }
        return voiceAgentStatus.accessibilityTrusted ? "语音代理可以写入当前光标" : "语音代理需要在系统设置中授权"
    }

    private var hotkeyMonitorStatus: String {
        guard agentRunning else { return "启动语音代理后检查" }
        switch voiceAgentStatus?.hotkeyMode {
        case "event_tap": return "已接管中键，按住说话、松开定稿"
        case "passive_middle_mouse": return "已监听中键；授权后自动切换为完整写入"
        default: return "监听未启动"
        }
    }

    private var hotwordStatus: String {
        if let status = voiceAgentStatus, status.hotwordsEnabled {
            return "已启用 \(status.hotwordCount) 条"
        }
        return hotwordsEnabled ? "等待语音代理重载 \(savedHotwordCount) 条" : "未启用"
    }

    private func latencyLabel(_ value: Int?) -> String {
        value.map { "\($0) ms" } ?? "尚无数据"
    }

    private func networkLabel(_ value: String) -> String {
        switch value {
        case "starting": return "准备中"
        case "connecting": return "正在连接"
        case "connected": return "已连接"
        case "streaming": return "流式接收中"
        case "completed", "closed": return "已完成"
        case "failed", "disconnected": return "连接异常"
        default: return "空闲"
        }
    }

    private func load() {
        provider = VoiceProviderConfigStore.read()
        loadProvider(provider)
        let hotwordConfig = VoiceHotwordConfigStore.read()
        hotwordsEnabled = hotwordConfig.enabled
        hotwordsText = hotwordConfig.words.joined(separator: "\n")
        savedHotwordCount = hotwordConfig.effectiveWords.count
        hotkeyChoice = VoiceHotkeyConfigStore.read().choice
        refreshAgentState()
    }

    private func saveHotwords() {
        do {
            let config = try VoiceASRHotwordConfig.validated(
                enabled: hotwordsEnabled,
                rawLines: hotwordsText
            )
            try VoiceHotwordConfigStore.write(config)
            hotwordsText = config.words.joined(separator: "\n")
            savedHotwordCount = config.effectiveWords.count
            hotwordMessage = config.enabled ? "已启用 \(config.effectiveWords.count) 条" : "已保存但未启用"
            notifyConfigurationChanged()
        } catch {
            hotwordMessage = error.localizedDescription
        }
    }

    private func clearHotwords() {
        VoiceHotwordConfigStore.remove()
        hotwordsEnabled = false
        hotwordsText = ""
        savedHotwordCount = 0
        hotwordMessage = "已清空"
        notifyConfigurationChanged()
    }

    private func notifyConfigurationChanged() {
        DistributedNotificationCenter.default().post(
            name: Notification.Name("com.rag-ime.voice.configuration-changed"),
            object: nil
        )
    }

    private func save() {
        do {
            try VoiceKeychainStore.saveLocal(
                provider: provider,
                appID: appID,
                accessToken: accessToken.isEmpty ? nil : accessToken,
                resourceID: resourceID,
                endpoint: endpoint,
                model: modelName
            )
            accessToken = ""
            tokenConfigured = true
            saveMessage = "已保存，语音代理会立即重载"
            DistributedNotificationCenter.default().post(
                name: Notification.Name("com.rag-ime.voice.configuration-changed"),
                object: nil
            )
        } catch {
            saveMessage = error.localizedDescription
        }
    }

    private func loadProvider(_ selected: VoiceASRProvider) {
        accessToken = ""
        appID = ""
        resourceID = VoiceKeychainStore.defaultResourceID
        endpoint = VoiceKeychainStore.defaultRealtimeEndpoint
        modelName = VoiceKeychainStore.defaultRealtimeModel
        if let credentials = VoiceKeychainStore.loadCredentials(provider: selected) {
            appID = credentials.appID
            resourceID = credentials.resourceID
            endpoint = credentials.endpoint.isEmpty ? VoiceKeychainStore.defaultRealtimeEndpoint : credentials.endpoint
            modelName = credentials.model.isEmpty ? VoiceKeychainStore.defaultRealtimeModel : credentials.model
        }
        tokenConfigured = VoiceKeychainStore.hasAccessToken(provider: selected)
        saveMessage = ""
    }

    private var credentialsReady: Bool {
        guard tokenConfigured else { return false }
        switch provider {
        case .nativeStreaming:
            return !appID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !resourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .realtimeWebSocket:
            return URL(string: endpoint)?.scheme?.lowercased().hasPrefix("ws") == true
                && !modelName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private func saveHotkey(_ choice: VoiceHotkeyChoice) {
        do {
            try VoiceHotkeyConfigStore.write(choice)
            saveMessage = "语音快捷键已切换为 \(choice.title)"
            notifyConfigurationChanged()
        } catch {
            saveMessage = error.localizedDescription
        }
    }

    private func toggleAgent() {
        let running = NSRunningApplication.runningApplications(withBundleIdentifier: "com.rag-ime.voice")
        if !running.isEmpty {
            running.forEach { _ = $0.terminate() }
            saveMessage = "语音代理已停止"
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { refreshAgentState() }
            return
        }
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.rag-ime.voice") else {
            saveMessage = "语音代理尚未安装，请先运行安装脚本"
            return
        }
        NSWorkspace.shared.openApplication(at: url, configuration: .init())
        saveMessage = "语音代理正在启动"
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { refreshAgentState() }
    }

    private func openPrivacyPane(_ pane: String) {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") else { return }
        NSWorkspace.shared.open(url)
    }

    private func refreshAgentState() {
        agentRunning = !NSRunningApplication.runningApplications(withBundleIdentifier: "com.rag-ime.voice").isEmpty
        voiceAgentStatus = agentRunning ? VoiceAgentStatusStore.read() : nil
    }
}
