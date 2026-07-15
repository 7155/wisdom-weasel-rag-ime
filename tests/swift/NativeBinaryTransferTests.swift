import Foundation

@main
struct NativeBinaryTransferTests {
    static func main() {
        for byteCount in [25 * 1024 * 1024, 50 * 1024 * 1024] {
            let ranges = NativeBinaryTransferPlan.chunkRanges(byteCount: byteCount)
            precondition(!ranges.isEmpty)
            precondition(ranges.first?.lowerBound == 0)
            precondition(ranges.last?.upperBound == byteCount)
            precondition(ranges.allSatisfy { $0.count <= NativeBinaryTransferPlan.chunkByteCount })
            precondition(zip(ranges, ranges.dropFirst()).allSatisfy { $0.upperBound == $1.lowerBound })

            let data = Data(repeating: 0x5a, count: byteCount)
            var decodedBytes = 0
            var maximumEncodedChunk = 0
            for range in ranges {
                let encoded = data.subdata(in: range).base64EncodedString()
                decodedBytes += Data(base64Encoded: encoded)?.count ?? 0
                maximumEncodedChunk = max(maximumEncodedChunk, encoded.utf8.count)
            }
            precondition(decodedBytes == byteCount)
            precondition(maximumEncodedChunk < 1024 * 1024)
        }
        print("NativeBinaryTransferTests: OK")
    }
}
