import SwiftUI

struct OverviewPage: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var navigation: ControlNavigationModel
    @State private var selectedProfile = "标准模式"

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let overview = model.overview {
                ScrollView {
                    VStack(alignment: .leading, spacing: ControlDesign.sectionSpacing) {
                        readinessSection(overview)
                        memorySection(overview.memory)
                        predictionSection(overview.lastPrediction)
                        actionSection
                    }
                    .padding(.horizontal, ControlDesign.pageHorizontalPadding)
                    .padding(.vertical, ControlDesign.pageVerticalPadding)
                    .frame(maxWidth: ControlDesign.contentMaxWidth, alignment: .leading)
                    .frame(maxWidth: .infinity, alignment: .center)
                }
            } else {
                EmptyState(symbol: "bolt.horizontal.circle", text: "正在连接本地管理服务")
            }
        }
        .onAppear { selectedProfile = model.overview?.profile ?? "标准模式" }
    }

    private var header: some View {
        HStack(spacing: 18) {
            RagImeAnimeCompanion(state: .idle, size: 58)
            PageHeader(title: "今日概览", subtitle: "输入法、本地预测、个人记忆与知识生成的实时状态")
            Spacer()
            Picker("运行模式", selection: profileSelection) {
                ForEach(["安全模式", "标准模式", "记忆增强", "调试模式"], id: \.self, content: Text.init)
            }
            .frame(width: 168)
            Button {
                Task { await model.toggleAI() }
            } label: {
                Label(
                    model.overview?.aiPaused == true ? "恢复 AI" : "暂停 AI",
                    systemImage: model.overview?.aiPaused == true ? "play.fill" : "pause.fill"
                )
            }
        }
        .padding(.horizontal, ControlDesign.pageHorizontalPadding)
        .padding(.vertical, 20)
    }

    private var profileSelection: Binding<String> {
        Binding(
            get: { selectedProfile },
            set: { value in
                selectedProfile = value
                Task { await model.applyProfile(value) }
            }
        )
    }

    private func readinessSection(_ overview: OverviewResponse) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            ControlSectionHeader(
                title: "现在可以用",
                trailing: overview.components.values.allSatisfy(\.ok) ? "全部就绪" : "有项目需要检查"
            )
            ControlSurface {
                HStack(spacing: 0) {
                    readinessItem(overview, id: "inputMethod", title: "鼠须管", symbol: "keyboard")
                    Divider().frame(height: 40)
                    readinessItem(overview, id: "predictor", title: "本地预测", symbol: "sparkles")
                    Divider().frame(height: 40)
                    readinessItem(overview, id: "hybridRag", title: "知识召回", symbol: "point.3.connected.trianglepath.dotted")
                    Divider().frame(height: 40)
                    readinessItem(overview, id: "foregroundContext", title: "前台上下文", symbol: "text.cursor")
                }
                .padding(.vertical, 8)
            }
        }
    }

    private func readinessItem(
        _ overview: OverviewResponse,
        id: String,
        title: String,
        symbol: String
    ) -> some View {
        let status = overview.components[id]
        return ControlReadinessItem(
            title: title,
            detail: status?.detail ?? "等待状态",
            symbol: symbol,
            ready: status?.ok == true && status?.status != "degraded"
        )
    }

    private func memorySection(_ memory: MemorySummary) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            ControlSectionHeader(title: "个人知识库", trailing: "本地 SQLite")
            ControlSurface {
                HStack(spacing: 0) {
                ControlMetricItem(
                    title: "输入事件",
                    value: "\(memory.eventCount)",
                    detail: "近期上下文",
                    symbol: "text.append",
                    tint: .blue
                )
                Divider().frame(height: 44)
                ControlMetricItem(
                    title: "可召回文档",
                    value: "\(memory.retrievalDocCount)",
                    detail: "BGE / BM25",
                    symbol: "doc.text.magnifyingglass",
                    tint: .teal
                )
                Divider().frame(height: 44)
                ControlMetricItem(
                    title: "主题记忆",
                    value: "\(memory.memoryBookCount)",
                    detail: "Memory Book",
                    symbol: "books.vertical",
                    tint: .orange
                )
                Divider().frame(height: 44)
                ControlMetricItem(
                    title: "待整理",
                    value: "\(memory.pendingCompileEvents)",
                    detail: memory.pendingCompileEvents == 0 ? "已同步" : "可生成草案",
                    symbol: "arrow.triangle.2.circlepath",
                    tint: memory.pendingCompileEvents == 0 ? .green : .orange
                )
                }
                .padding(.vertical, 8)
            }
        }
    }

    private func predictionSection(_ prediction: LastPrediction) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            ControlSectionHeader(
                title: "最近一次前台建议",
                trailing: prediction.totalLatencyMs.map { String(Int($0)) + " ms" } ?? "暂无"
            )
            HStack(alignment: .top, spacing: 18) {
                VStack(alignment: .leading, spacing: 12) {
                    if prediction.triggerReason == nil {
                        Text("在鼠须管中完成一小段输入后，这里会显示实际候选与来源。")
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 14)
                    } else {
                        Text(prediction.visibleCandidate ?? "本次没有通过质量门的候选")
                            .font(.system(size: 20, weight: .medium))
                            .lineLimit(3)
                            .frame(maxWidth: .infinity, minHeight: 52, alignment: .topLeading)
                        HStack(spacing: 18) {
                            ForEach(Array(Set(prediction.sourceTypes ?? [])).sorted(), id: \.self) { source in
                                SourceLaneLabel(source: source)
                            }
                            Spacer()
                            Label(prediction.contextSource ?? "上下文未知", systemImage: "text.quote")
                            Text("\(prediction.providerCallCount ?? 0) 次调用")
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Divider().frame(minHeight: 72)
                VStack(alignment: .leading, spacing: 9) {
                    Text("触发方式").font(.caption).foregroundStyle(.secondary)
                    Text(prediction.triggerReason ?? "等待前台输入")
                        .font(.callout.weight(.medium))
                    HStack(spacing: 7) {
                        ControlShortcutKey(text: "Tab")
                        Text("首项")
                        ControlShortcutKey(text: "⌥ 2–4")
                        Text("其他候选")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                .frame(width: 260, alignment: .leading)
            }
            .padding(18)
            .background(ControlDesign.quietSurface)
            .clipShape(RoundedRectangle(cornerRadius: ControlDesign.surfaceRadius))
            .overlay(RoundedRectangle(cornerRadius: ControlDesign.surfaceRadius).stroke(ControlDesign.hairline, lineWidth: 0.7))
        }
    }

    private var actionSection: some View {
        HStack(spacing: 12) {
            Text("常用操作").font(.callout.weight(.semibold)).foregroundStyle(.secondary)
            Button {
                navigation.destination = .ragAndModels
            } label: {
                Label("打开知识工作台", systemImage: "sparkles.rectangle.stack")
            }
            .buttonStyle(.borderedProminent)
            Button {
                navigation.destination = .voiceInput
            } label: {
                Label("语音输入", systemImage: "waveform.and.mic")
            }
            Button {
                navigation.destination = .diagnostics
            } label: {
                Label("实时诊断", systemImage: "waveform.path.ecg")
            }
            Spacer()
            Button {
                Task { await model.run(action: "repair_launch_agents") }
            } label: {
                Label("检查运行组件", systemImage: "wrench.and.screwdriver")
            }
        }
        .padding(.vertical, 4)
    }
}
