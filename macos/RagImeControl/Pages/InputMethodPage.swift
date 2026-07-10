import SwiftUI

struct InputMethodPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "输入法", subtitle: "管理提交后预测、快捷键、候选界面与模糊音")
                Spacer()
            }
            .padding(20)
            PendingApplyBanner()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    ForEach(model.sections(ids: ["interaction", "display", "activeRag", "pinyin"])) { section in
                        SchemaSectionView(section: section)
                        Divider()
                    }
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
            }
        }
    }
}
