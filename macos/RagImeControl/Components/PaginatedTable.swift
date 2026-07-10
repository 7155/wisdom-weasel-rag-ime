import AppKit
import SwiftUI

struct PaginatedTable: NSViewRepresentable {
    let columns: [String]
    let rows: [TableRow]
    var onSelect: ((Int) -> Void)?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSScrollView {
        let table = NSTableView()
        table.delegate = context.coordinator
        table.dataSource = context.coordinator
        table.usesAlternatingRowBackgroundColors = true
        table.rowHeight = 30
        table.selectionHighlightStyle = .regular
        for (index, title) in columns.enumerated() {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("c\(index)"))
            column.title = title
            column.minWidth = index == 0 ? 150 : 90
            column.resizingMask = .autoresizingMask
            table.addTableColumn(column)
        }
        let scroll = NSScrollView()
        scroll.documentView = table
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        return scroll
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        context.coordinator.parent = self
        (nsView.documentView as? NSTableView)?.reloadData()
    }

    final class Coordinator: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        var parent: PaginatedTable
        init(_ parent: PaginatedTable) { self.parent = parent }
        func numberOfRows(in tableView: NSTableView) -> Int { parent.rows.count }
        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            guard let tableColumn, let index = tableView.tableColumns.firstIndex(of: tableColumn), row < parent.rows.count else { return nil }
            let identifier = NSUserInterfaceItemIdentifier("cell")
            let cell = (tableView.makeView(withIdentifier: identifier, owner: nil) as? NSTableCellView) ?? NSTableCellView()
            if cell.textField == nil {
                let text = NSTextField(labelWithString: "")
                text.lineBreakMode = .byTruncatingTail
                text.translatesAutoresizingMaskIntoConstraints = false
                cell.addSubview(text)
                cell.textField = text
                NSLayoutConstraint.activate([
                    text.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 6),
                    text.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -6),
                    text.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
                ])
                cell.identifier = identifier
            }
            cell.textField?.stringValue = index < parent.rows[row].values.count ? parent.rows[row].values[index] : ""
            return cell
        }
        func tableViewSelectionDidChange(_ notification: Notification) {
            guard let table = notification.object as? NSTableView, table.selectedRow >= 0 else { return }
            parent.onSelect?(table.selectedRow)
        }
    }
}
