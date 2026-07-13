import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ConfigurationPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "配置与迁移", subtitle: "集中调整上下文、规划与记忆，并迁移本地数据")
                Spacer()
                Toggle("高级设置", isOn: $model.expertMode)
                    .toggleStyle(.switch)
                    .fixedSize()
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 22)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    settingsSection
                    Divider()
                    configurationImport
                    Divider()
                    backupAndRestore
                    if !model.configurationStatus.isEmpty {
                        Label(model.configurationStatus, systemImage: "info.circle")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 22)
                .frame(maxWidth: 960, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private var settingsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("常用设置", systemImage: "slider.horizontal.3").font(.title3.weight(.semibold))
            ForEach(model.sections(ids: ["context", "planning", "memory", "pinyin"])) { section in
                SchemaSectionView(section: section)
                if section.id != model.sections(ids: ["context", "planning", "memory", "pinyin"]).last?.id {
                    Divider()
                }
            }
        }
    }

    private var configurationImport: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("配置文件", systemImage: "doc.badge.gearshape").font(.title3.weight(.semibold))
            HStack(spacing: 12) {
                Button(action: chooseConfiguration) {
                    Label("选择配置", systemImage: "folder")
                }
                if !model.configurationPath.isEmpty {
                    Text(URL(fileURLWithPath: model.configurationPath).lastPathComponent)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let preview = model.configurationPreview {
                    Label(
                        preview.valid ? "校验通过 · \(preview.settingCount) 项设置" : "配置有 \(preview.errors.count) 个问题",
                        systemImage: preview.valid ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
                    )
                    .foregroundStyle(preview.valid ? .green : .orange)
                }
                Spacer()
                Button {
                    Task { await model.applyConfiguration() }
                } label: {
                    Label("导入", systemImage: "square.and.arrow.down")
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.configurationPreview?.valid != true || model.configurationBusy)
            }
            if let preview = model.configurationPreview, !preview.errors.isEmpty {
                Text(preview.errors.joined(separator: "\n"))
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .textSelection(.enabled)
            }
            Text("推荐使用带完整注释的 rag-ime.config.yaml。文件若包含 API Key，会自动收紧为 0600；密钥导入 Keychain，备份包不携带密钥。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var backupAndRestore: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("备份与恢复", systemImage: "externaldrive.badge.timemachine").font(.title3.weight(.semibold))
            HStack(spacing: 12) {
                Button(action: chooseBackupDestination) {
                    Label("导出完整备份", systemImage: "archivebox")
                }
                Button(action: chooseRestoreArchive) {
                    Label("选择备份", systemImage: "externaldrive")
                }
                Spacer()
                if let restore = model.restorePreview {
                    Text("输入 \(restore.databaseCounts["input_events"] ?? 0) · 记忆 \(restore.databaseCounts["memory_items"] ?? 0) · 任务 \(restore.databaseCounts["planning_tasks"] ?? 0)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button(role: .destructive) {
                        Task { await model.applyPortableRestore() }
                    } label: {
                        Label("恢复", systemImage: "arrow.counterclockwise")
                    }
                    .disabled(model.configurationBusy)
                }
            }
            Text("备份包含本地数据库、管理设置和 Rime 自定义 YAML；不包含 API Key、模型权重、缓存与日志。恢复前自动生成回滚包。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func chooseConfiguration() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [
            .json,
            UTType(filenameExtension: "yaml") ?? .plainText,
            UTType(filenameExtension: "yml") ?? .plainText,
        ]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.previewConfiguration(at: url.path) }
    }

    private func chooseBackupDestination() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "rag-ime-backup.ragime-backup"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.exportPortableBackup(to: url.path) }
    }

    private func chooseRestoreArchive() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "ragime-backup") ?? .zip, .zip]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.previewPortableRestore(from: url.path) }
    }
}
