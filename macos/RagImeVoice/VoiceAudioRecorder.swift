import AVFoundation
import Foundation

final class VoiceAudioRecorder {
    var onPCM: ((Data) -> Void)?
    var onLevel: ((Double) -> Void)?

    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private(set) var isRecording = false

    static var permissionGranted: Bool {
        AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    static var authorizationName: String {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return "authorized"
        case .notDetermined: return "not_determined"
        case .denied: return "denied"
        case .restricted: return "restricted"
        @unknown default: return "unknown"
        }
    }

    static func requestPermission(_ completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: completion(true)
        case .notDetermined: AVCaptureDevice.requestAccess(for: .audio, completionHandler: completion)
        default: completion(false)
        }
    }

    func start() throws {
        guard !isRecording else { return }
        let input = engine.inputNode
        let sourceFormat = input.outputFormat(forBus: 0)
        guard sourceFormat.channelCount > 0,
              let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 16_000,
                channels: 1,
                interleaved: true
              ),
              let converter = AVAudioConverter(from: sourceFormat, to: targetFormat) else {
            throw VoiceRecorderError.unsupportedFormat
        }
        self.converter = converter
        input.installTap(onBus: 0, bufferSize: 2_048, format: sourceFormat) { [weak self] buffer, _ in
            self?.consume(buffer, targetFormat: targetFormat)
        }
        engine.prepare()
        do {
            try engine.start()
            isRecording = true
        } catch {
            input.removeTap(onBus: 0)
            self.converter = nil
            throw error
        }
    }

    func stop() {
        guard isRecording else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        converter = nil
        isRecording = false
    }

    private func consume(_ buffer: AVAudioPCMBuffer, targetFormat: AVAudioFormat) {
        guard let converter else { return }
        let ratio = targetFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(max(1, ceil(Double(buffer.frameLength) * ratio) + 32))
        guard let output = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
        var supplied = false
        var conversionError: NSError?
        let status = converter.convert(to: output, error: &conversionError) { _, inputStatus in
            if supplied {
                inputStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            inputStatus.pointee = .haveData
            return buffer
        }
        guard conversionError == nil,
              status == .haveData || status == .inputRanDry,
              output.frameLength > 0 else { return }
        let audioBuffer = output.audioBufferList.pointee.mBuffers
        guard let bytes = audioBuffer.mData, audioBuffer.mDataByteSize > 0 else { return }
        onPCM?(Data(bytes: bytes, count: Int(audioBuffer.mDataByteSize)))
        onLevel?(Self.level(from: buffer))
    }

    private static func level(from buffer: AVAudioPCMBuffer) -> Double {
        guard let channels = buffer.floatChannelData, buffer.frameLength > 0 else { return 0.15 }
        let samples = channels[0]
        var sum: Float = 0
        for index in 0..<Int(buffer.frameLength) {
            let value = samples[index]
            sum += value * value
        }
        let rms = max(Double(sqrt(sum / Float(buffer.frameLength))), 0.000_001)
        let decibels = 20 * log10(rms)
        let normalized = min(1, max(0, (decibels + 55) / 45))
        // Human speech usually lives around -35...-15 dB. A logarithmic curve
        // makes that range visibly expressive without letting room noise pin
        // the waveform open.
        return min(1, max(0.04, pow(normalized, 0.68)))
    }
}

enum VoiceRecorderError: LocalizedError {
    case unsupportedFormat

    var errorDescription: String? { "当前麦克风格式无法转换为 16 kHz PCM" }
}
