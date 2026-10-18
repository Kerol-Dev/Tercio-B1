#pragma once
// -----------------------------------------------------------------------------
// Constants, angles and frame transforms for the FOC core.
//
// float32 only: this runs in the current-loop interrupt, where the FPU does
// single precision in hardware and double would be software-emulated
// (-Wdouble-promotion clean).
//
// Electrical angles are 32-bit binary angles (one turn = 2^32), so they wrap
// for free and an encoder count maps onto them exactly.
//
// Transforms are amplitude-invariant: a balanced three-phase set of peak I
// has |αβ| = I, and in the dq frame vd, vq, id, iq are per-phase peak values.
// So vd = R·id holds with R the phase (line-to-neutral) resistance.
// -----------------------------------------------------------------------------
#include <cmath>
#include <cstdint>

namespace foc {

inline constexpr float kPi = 3.14159265358979f;
inline constexpr float kTwoPi = 6.28318530717959f;
inline constexpr float kSqrt3 = 1.73205080756888f;
inline constexpr float kInvSqrt3 = 0.577350269189626f;
inline constexpr float kSqrt3Over2 = 0.866025403784439f;

using Angle = uint32_t;
inline constexpr float kRadPerAngle = kTwoPi / 4294967296.0f;
inline constexpr float kAnglePerRad = 4294967296.0f / kTwoPi;

// Signed radians in [-π, π).
inline float toRadians(Angle a) { return static_cast<float>(static_cast<int32_t>(a)) * kRadPerAngle; }
// Any number of turns; wraps modulo one turn.
inline Angle fromRadians(float rad) {
  return static_cast<Angle>(static_cast<int64_t>(rad * kAnglePerRad));
}

// sin and cos of a binary angle. The F1 port replaces this with the G4's
// CORDIC (one 6-cycle q31 operation gives both).
inline void sinCos(Angle a, float& s, float& c) {
  const float r = toRadians(a);
  s = std::sin(r);
  c = std::cos(r);
}

inline float clamp(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }

struct Abc {
  float a, b, c;
};
struct AlphaBeta {
  float alpha, beta;
};
struct Dq {
  float d, q;
};

// Uses all three phases, so a common-mode offset on the samples cancels.
inline AlphaBeta clarke(const Abc& x) {
  return {(2.0f * x.a - x.b - x.c) * (1.0f / 3.0f), (x.b - x.c) * kInvSqrt3};
}
inline Abc inverseClarke(const AlphaBeta& v) {
  return {v.alpha, -0.5f * v.alpha + kSqrt3Over2 * v.beta, -0.5f * v.alpha - kSqrt3Over2 * v.beta};
}
inline Dq park(const AlphaBeta& x, float s, float c) {
  return {x.alpha * c + x.beta * s, -x.alpha * s + x.beta * c};
}
inline AlphaBeta inversePark(const Dq& x, float s, float c) {
  return {x.d * c - x.q * s, x.d * s + x.q * c};
}

}  // namespace foc
