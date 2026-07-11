import AppKit
import SwiftUI

struct VoiceInputPage: View {
    @State private var appID = ""
    @State private var accessToken = ""
    @State private var resourceID = VoiceKeychainStore.defaultResourceID
    @State private var tokenConfigured = false
    @State private var saveMessage = ""
    @State private var agentRunning = false
    @State private var voiceAgentStatus: VoiceAgentStatus?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "语音输入", subtitle: "豆包 ASR 2.0 边说边写；最终结果原位定稿")
                Spacer()
            }
            .padding(20)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    statusSection
                    if let telemetry = voiceAgentStatus?.telemetry {
                        Divider()
                        telemetrySection(telemetry)
                    }
                    Divider()
                    credentialSection
                    Divider()
                    behaviorSection
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
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
            voiceStatusRow("辅助功能", ok: voiceAgentStatus?.accessibilityTrusted == true, detail: accessibilityStatus)
            voiceStatusRow("麦克风", ok: voiceAgentStatus?.microphoneAuthorization == "authorized", detail: microphoneStatus)
            voiceStatusRow("豆包凭据", ok: tokenConfigured && !appID.isEmpty, detail: tokenConfigured ? "已安全存入 Keychain" : "尚未配置")
            HStack {
                Button("打开隐私设置", systemImage: "hand.raised") {
                    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                }
                Button(agentRunning ? "停止语音代理" : "启动语音代理", systemImage: agentRunning ? "stop.fill" : "play.fill") {
                    toggleAgent()
                }
                .disabled(!tokenConfigured || appID.isEmpty)
            }
        }
    }

    private var credentialSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("豆包流式语音识别 2.0").font(.headline)
            LabeledContent("App ID") {
                TextField("App ID", text: $appID).textFieldStyle(.roundedBorder).frame(width: 310)
            }
            LabeledContent("Access Token") {
                SecureField(tokenConfigured ? "已配置，留空则保持不变" : "Access Token", text: $accessToken)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 310)
            }
            LabeledContent("Resource ID") {
                TextField("Resource ID", text: $resourceID).textFieldStyle(.roundedBorder).frame(width: 310)
            }
            HStack {
                Button("保存到 Keychain", systemImage: "key.fill") { save() }
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
            LabeledContent("按住说话") { Text("⌥ Space").font(.system(.body, design: .monospaced).weight(.semibold)) }
            LabeledContent("松开") { Text("发送终帧并原位定稿") }
            LabeledContent("Esc") { Text("取消并移除本次临时转写") }
            LabeledContent("隐私") { Text("密码、账号与 Secure Input 输入框不启动录音，也不写入历史") }
        }
    }

    private func voiceStatusRow(_ title: String, ok: Bool, detail: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .foregroundStyle(ok ? Color.green : Color.orange)
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
        if let credentials = VoiceKeychainStore.loadCredentials() {
            appID = credentials.appID
            resourceID = credentials.resourceID
        }
        tokenConfigured = VoiceKeychainStore.hasAccessToken
        refreshAgentState()
    }

    private func save() {
        do {
            try VoiceKeychainStore.save(
                appID: appID,
                accessToken: accessToken.isEmpty ? nil : accessToken,
                resourceID: resourceID
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

    private func refreshAgentState() {
        agentRunning = !NSRunningApplication.runningApplications(withBundleIdentifier: "com.rag-ime.voice").isEmpty
        voiceAgentStatus = agentRunning ? VoiceAgentStatusStore.read() : nil
    }
}
