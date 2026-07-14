import AppKit
import ImageIO
import SwiftUI

@MainActor
private final class RagImeCompanionArtworkStore {
    static let shared = RagImeCompanionArtworkStore()

    private let images: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 12
        cache.totalCostLimit = 20 * 1024 * 1024
        return cache
    }()

    func image(named name: String, maximumPixelSize: Int) async -> NSImage? {
        let bucket = maximumPixelSize <= 192 ? 160 : 512
        let key = "\(name)@\(bucket)" as NSString
        if let cached = images.object(forKey: key) { return cached }
        guard let url = Bundle.main.url(forResource: name, withExtension: "png") else { return nil }

        let cgImage = await Task.detached(priority: .utility) { () -> CGImage? in
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: bucket,
                kCGImageSourceShouldCacheImmediately: true,
            ]
            return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
        }.value
        guard let cgImage else { return nil }

        let image = NSImage(cgImage: cgImage, size: .zero)
        images.setObject(image, forKey: key, cost: max(1, cgImage.width * cgImage.height * 4))
        return image
    }
}

enum RagImeCompanionState: Equatable {
    case idle
    case listening
    case thinking
    case done
    case warning

    var accent: Color {
        switch self {
        case .idle: return Color(red: 0.08, green: 0.55, blue: 0.58)
        case .listening: return Color(red: 0.04, green: 0.67, blue: 0.61)
        case .thinking: return Color(red: 0.30, green: 0.42, blue: 0.83)
        case .done: return Color(red: 0.16, green: 0.64, blue: 0.35)
        case .warning: return Color(red: 0.91, green: 0.46, blue: 0.16)
        }
    }

    var animeAssetName: String {
        switch self {
        case .idle: return "RagImeCompanionIdle"
        case .listening: return "RagImeCompanionListening"
        case .thinking: return "RagImeCompanionThinking"
        case .done: return "RagImeCompanionDone"
        case .warning: return "RagImeCompanionWarning"
        }
    }

    var fullAnimeAssetName: String {
        "\(animeAssetName)Full"
    }
}

/// An original book-shaped companion shared by the control center and voice UI.
struct RagImeCompanionMark: View {
    let state: RagImeCompanionState
    var level: Double = 0
    var size: CGFloat = 44
    var showsStatusBadge = true

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Circle()
                .fill(state.accent.opacity(0.10))
                .frame(width: size, height: size)
                .scaleEffect(listeningScale)

            HStack(spacing: size * 0.035) {
                page(rotation: -4)
                page(rotation: 4)
            }
            .offset(y: -size * 0.01)
            .rotationEffect(.degrees(bookRotation))

            HStack(spacing: size * 0.16) {
                Circle().fill(Color.primary.opacity(0.68))
                Circle().fill(Color.primary.opacity(0.68))
            }
            .frame(width: size * 0.30, height: size * 0.055)
            .offset(y: -size * 0.055)

            Capsule()
                .fill(Color.primary.opacity(0.50))
                .frame(width: mouthWidth, height: max(1.5, size * 0.038))
                .offset(y: size * 0.10)

            RoundedRectangle(cornerRadius: 1.5)
                .fill(Color(red: 0.97, green: 0.43, blue: 0.30))
                .frame(width: size * 0.075, height: size * 0.29)
                .offset(x: size * 0.24, y: size * 0.17)

            if showsStatusBadge {
                statusBadge
                    .offset(x: size * 0.34, y: -size * 0.34)
            }
        }
        .frame(width: size * 1.08, height: size * 1.08)
        .animation(RagImeMotion.spring(reduceMotion: reduceMotion), value: level)
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: state)
        .accessibilityHidden(true)
    }

    private func page(rotation: Double) -> some View {
        RoundedRectangle(cornerRadius: max(3, size * 0.12))
            .fill(state.accent.opacity(0.96))
            .frame(width: size * 0.34, height: size * 0.50)
            .overlay(alignment: .leading) {
                Capsule()
                    .fill(Color.white.opacity(0.30))
                    .frame(width: max(1.5, size * 0.035), height: size * 0.34)
                    .padding(.leading, size * 0.075)
            }
            .rotationEffect(.degrees(rotation))
    }

    @ViewBuilder
    private var statusBadge: some View {
        switch state {
        case .listening:
            HStack(spacing: 1.5) {
                ForEach(0..<3, id: \.self) { index in
                    Capsule()
                        .fill(state.accent)
                        .frame(
                            width: max(2, size * 0.045),
                            height: size * (0.10 + CGFloat(min(max(level, 0), 1)) * (0.05 + CGFloat(index) * 0.035))
                        )
                }
            }
        case .thinking:
            ProgressView().controlSize(.mini).tint(state.accent)
        case .done:
            Image(systemName: "checkmark.circle.fill").foregroundStyle(state.accent)
        case .warning:
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(state.accent)
        case .idle:
            Circle().fill(state.accent).frame(width: size * 0.12, height: size * 0.12)
        }
    }

    private var listeningScale: CGFloat {
        guard state == .listening, !reduceMotion else { return 1 }
        return 0.97 + CGFloat(min(max(level, 0), 1)) * 0.07
    }

    private var bookRotation: Double {
        guard state == .listening, !reduceMotion else { return 0 }
        return (min(max(level, 0), 1) - 0.35) * 3.2
    }

    private var mouthWidth: CGFloat {
        switch state {
        case .warning: return size * 0.12
        case .listening: return size * (0.15 + CGFloat(min(max(level, 0), 1)) * 0.08)
        default: return size * 0.18
        }
    }
}

/// Original anime companion artwork for surfaces large enough to preserve expression.
/// The code-native book mark remains the fallback when the bundled artwork is unavailable.
struct RagImeAnimeCompanion: View {
    let state: RagImeCompanionState
    var level: Double = 0
    var size: CGFloat = 56
    var animatesAmbientMotion = true

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var floating = false
    @State private var artwork: NSImage?

    var body: some View {
        ZStack {
            if let artwork {
                Image(nsImage: artwork)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: size, height: size)
                    .offset(y: shouldFloat ? (floating ? -1.4 : 1.2) : 0)
                    .scaleEffect(listeningScale)
                    .id(state.animeAssetName)
                    .transition(.opacity.combined(with: .scale(scale: 0.94)))
            } else {
                RagImeCompanionMark(
                    state: state,
                    level: level,
                    size: size * 0.82,
                    showsStatusBadge: false
                )
            }
        }
        .frame(width: size, height: size)
        .shadow(color: Color.black.opacity(0.10), radius: 3, y: 1.5)
        .animation(RagImeMotion.spring(reduceMotion: reduceMotion), value: level)
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: state)
        .task(id: state.animeAssetName) {
            let name = state.animeAssetName
            artwork = nil
            let loaded = await RagImeCompanionArtworkStore.shared.image(
                named: name,
                maximumPixelSize: 160
            )
            guard !Task.isCancelled, state.animeAssetName == name else { return }
            artwork = loaded
        }
        .onAppear { updateFloatingAnimation() }
        .onChange(of: state) { _ in updateFloatingAnimation() }
        .onChange(of: reduceMotion) { _ in updateFloatingAnimation() }
        .accessibilityHidden(true)
    }

    private var listeningScale: CGFloat {
        guard state == .listening, !reduceMotion else { return 1 }
        return 0.98 + CGFloat(min(max(level, 0), 1)) * 0.05
    }

    private var shouldFloat: Bool {
        animatesAmbientMotion && !reduceMotion && (state == .listening || state == .thinking)
    }

    private func updateFloatingAnimation() {
        floating = false
        guard shouldFloat else { return }
        withAnimation(.easeInOut(duration: RagImeMotion.Duration.companionFloat).repeatForever(autoreverses: true)) {
            floating = true
        }
    }
}

/// Full-body artwork for empty states and Agent stages where the character is part of the experience.
struct RagImeFullBodyCompanion: View {
    let state: RagImeCompanionState
    var size: CGFloat = 180
    var animatesAmbientMotion = true

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var floating = false
    @State private var artwork: NSImage?

    var body: some View {
        Group {
            if let artwork {
                Image(nsImage: artwork)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .id(state.fullAnimeAssetName)
                    .transition(.opacity.combined(with: .scale(scale: 0.97)))
            } else {
                RagImeAnimeCompanion(state: state, size: size * 0.64)
            }
        }
        .frame(width: size, height: size)
        .offset(y: shouldFloat ? (floating ? -2.5 : 2) : 0)
        .shadow(color: Color.black.opacity(0.09), radius: 5, y: 2)
        .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: state)
        .task(id: state.fullAnimeAssetName) {
            let name = state.fullAnimeAssetName
            artwork = nil
            let loaded = await RagImeCompanionArtworkStore.shared.image(
                named: name,
                maximumPixelSize: 512
            )
            guard !Task.isCancelled, state.fullAnimeAssetName == name else { return }
            artwork = loaded
        }
        .onAppear { updateFloatingAnimation() }
        .onChange(of: state) { _ in updateFloatingAnimation() }
        .onChange(of: reduceMotion) { _ in updateFloatingAnimation() }
        .accessibilityHidden(true)
    }

    private var shouldFloat: Bool {
        animatesAmbientMotion && !reduceMotion && (state == .listening || state == .thinking)
    }

    private func updateFloatingAnimation() {
        floating = false
        guard shouldFloat else { return }
        withAnimation(.easeInOut(duration: RagImeMotion.Duration.companionFloat).repeatForever(autoreverses: true)) {
            floating = true
        }
    }
}
