import SwiftUI

struct OverviewPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var selectedProfile = "标准模式"

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let overview = model.overview {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        componentSection(overview)
                        predictionSection(overview.lastPrediction)
                        actionSection
                    }
                    .padding(24)
                    .frame(maxWidth: 780, alignment: .leading)
                }
            } else {
                EmptyState(symbol: "bolt.horizontal.circle", text: "正在连接本地管理服务")
            }
        }
        .onAppear { selectedProfile = model.overview?.profile ?? "标准模式" }
    }

    private var header: some View {
        HStack(spacing: 14) {
            PageHeader(title: "RAG-IME", subtitle: "输入法、记忆与模型运行概览")
            Spacer()
            Picker("运行模式", selection: $selectedProfile) {
                ForEach(["安全模式", "标准模式", "记忆增强", "调试模式"], id: \.self, content: Text.init)
            }
            .frame(width: 150)
            .onChange(of: selectedProfile) { value in Task { await model.applyProfile(value) } }
            Button {
                Task { await model.toggleAI() }
            } label: {
                Label(model.overview?.aiPaused == true ? "恢复 AI" : "暂停 AI", systemImage: model.overview?.aiPaused == true ? "play.fill" : "pause.fill")
            }
        }
        .padding(20)
    }

    private func componentSection(_ overview: OverviewResponse) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("运行状态").font(.headline).padding(.bottom, 8)
            ForEach(overview.components.values.sorted { $0.id < $1.id }) { status in
                StatusRow(status: status)
                Divider()
            }
        }
    }

    private func predictionSection(_ prediction: LastPrediction) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("最近一次预测").font(.headline)
            if prediction.triggerReason == nil {
                Text("还没有可展示的预测记录").foregroundStyle(.secondary).padding(.vertical, 12)
            } else {
                LabeledContent("触发", value: prediction.triggerReason ?? "-")
                LabeledContent("上下文", value: prediction.contextSource ?? "-")
                LabeledContent("结果", value: prediction.visibleCandidate ?? "未显示候选")
                LabeledContent("总耗时", value: "\(Int(prediction.totalLatencyMs ?? 0)) ms")
                LabeledContent("模型调用", value: "\(prediction.providerCallCount ?? 0) 次")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.5))
    }

    private var actionSection: some View {
        HStack {
            Button {
                Task { await model.run(action: "repair_launch_agents") }
            } label: {
                Label("检查并修复", systemImage: "wrench.and.screwdriver")
            }
            Button {
                model.destination = .diagnostics
            } label: {
                Label("打开实时诊断", systemImage: "waveform.path.ecg")
            }
            Spacer()
        }
    }
}
