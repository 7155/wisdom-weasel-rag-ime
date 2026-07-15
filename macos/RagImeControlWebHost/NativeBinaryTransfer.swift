import Foundation

enum NativeBinaryTransferPlan {
    static let chunkByteCount = 512 * 1024

    static func chunkRanges(byteCount: Int) -> [Range<Int>] {
        guard byteCount > 0 else { return [] }
        var ranges: [Range<Int>] = []
        ranges.reserveCapacity((byteCount + chunkByteCount - 1) / chunkByteCount)
        var offset = 0
        while offset < byteCount {
            let end = min(byteCount, offset + chunkByteCount)
            ranges.append(offset..<end)
            offset = end
        }
        return ranges
    }
}
