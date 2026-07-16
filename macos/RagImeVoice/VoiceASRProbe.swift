import Foundation

enum VoiceASRProbe {
    private final class ResultBox: @unchecked Sendable {
        private let lock = NSLock()
        private var finalText = ""
        private var failure = ""

        func apply(_ event: VoiceASREvent) {
            lock.lock()
            defer { lock.unlock() }
            switch event {
            case .partial(let text), .final(let text): finalText = text
            case .failure(let message): failure = message
            case .responseMetadata, .transport: break
            }
        }

        func snapshot() -> (text: String, failure: String) {
            lock.lock()
            defer { lock.unlock() }
            return (finalText, failure)
        }
    }

    static func run(pcmPath: String) -> Int32 {
        guard let credentials = VoiceKeychainStore.loadCredentials(allowLegacyFallback: true),
              credentials.isComplete else {
            fputs("voice probe: credentials missing\n", stderr)
            return 2
        }
        guard let pcm = try? Data(contentsOf: URL(fileURLWithPath: pcmPath)), !pcm.isEmpty else {
            fputs("voice probe: PCM file missing or empty\n", stderr)
            return 2
        }

        let completed = DispatchSemaphore(value: 0)
        let resultBox = ResultBox()
        let client = VolcengineStreamingASRClient(
            credentials: credentials,
            hotwordConfig: VoiceHotwordConfigStore.read()
        ) { event in
            resultBox.apply(event)
            switch event {
            case .final, .failure: completed.signal()
            case .partial, .responseMetadata, .transport: break
            }
        }
        client.start()
        Thread.sleep(forTimeInterval: 0.35)
        var offset = 0
        while offset < pcm.count {
            let end = min(offset + VolcengineStreamingASRClient.audioChunkBytes, pcm.count)
            client.appendPCM(pcm.subdata(in: offset..<end))
            offset = end
            Thread.sleep(forTimeInterval: 0.2)
        }
        client.finish()
        let outcome = completed.wait(timeout: .now() + 15)
        client.cancel()
        if outcome == .timedOut {
            fputs("voice probe: timed out\n", stderr)
            return 3
        }
        let result = resultBox.snapshot()
        if !result.failure.isEmpty {
            fputs("voice probe: \(result.failure)\n", stderr)
            return 4
        }
        print("voice probe transcript: \(result.text)")
        return result.text.isEmpty ? 5 : 0
    }
}
