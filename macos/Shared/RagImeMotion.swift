import QuartzCore
import SwiftUI

/// Shared motion language for the control center and voice surfaces.
/// Continuous motion is deliberately scarce: one ambient cue, one progress cue,
/// and one streaming caret are the default budget for a visible surface.
enum RagImeMotion {
    enum Duration {
        static let micro: TimeInterval = 0.10
        static let entrance: TimeInterval = 0.14
        static let transition: TimeInterval = 0.18
        static let stateChange: TimeInterval = 0.24
        static let thinkingPulse: TimeInterval = 0.56
        static let ambientPulse: TimeInterval = 0.72
        static let progressSpin: TimeInterval = 0.90
        static let companionFloat: TimeInterval = 1.60
        static let orbit: TimeInterval = 2.40
    }

    enum Distance {
        static let tiny: CGFloat = 3
        static let small: CGFloat = 5
    }

    enum Budget {
        static let maximumContinuousAnimationsPerSurface = 3
    }

    static let stagger: TimeInterval = 0.04

    static func entrance(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: Duration.entrance)
    }

    static func transition(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeOut(duration: Duration.transition)
    }

    static func stateChange(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .easeInOut(duration: Duration.stateChange)
    }

    static func spring(reduceMotion: Bool) -> Animation? {
        reduceMotion ? nil : .spring(response: 0.28, dampingFraction: 0.88)
    }

    static func timingFunction(_ name: CAMediaTimingFunctionName = .easeOut) -> CAMediaTimingFunction {
        CAMediaTimingFunction(name: name)
    }
}

/// Immediate press feedback shared by the native control surfaces. It never
/// delays the action itself; only the already-committed visual state animates.
struct RagImePressButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.975 : 1)
            .opacity(configuration.isPressed ? 0.72 : 1)
            .animation(
                reduceMotion ? nil : .easeOut(duration: RagImeMotion.Duration.micro),
                value: configuration.isPressed
            )
    }
}
