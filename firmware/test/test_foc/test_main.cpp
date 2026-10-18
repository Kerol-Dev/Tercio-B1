// Host-side tests: the FOC core driving the simulated motor (docs/07-firmware.md §7.7).
// Run with: pio test -e native
#include <unity.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "app/Joint.h"
#include "foc/Calibration.h"
#include "foc/FocCore.h"
#include "foc/Svpwm.h"
#include "sim/Bench.h"

namespace {

constexpr double kTwoPi = 6.283185307179586;

// Firmware configuration for a bench whose motor and encoder mounting are known exactly (what
// calibration would find), so a test can isolate the current loop.
foc::FocCore::Config knownMotor(const sim::Bench& b, float bandwidthHz = 1500.0f) {
  const sim::MotorParams& m = b.motor().params();
  const sim::BenchConfig& bc = b.config();
  foc::FocCore::Config c;
  c.tickPeriod = static_cast<float>(bc.pwmPeriod);
  c.ampsPerCount = b.ampsPerCount();
  c.busVoltsPerCount = b.busVoltsPerCount();
  for (int x = 0; x < 3; ++x) c.currentOffset[x] = static_cast<float>(2048.0 + bc.csaOffsetVolts[x] / bc.vref * 4096.0);
  c.encoderBits = static_cast<uint8_t>(bc.encoderBits);
  c.encoderDirection = static_cast<int8_t>(bc.encoderDirection);
  c.polePairs = static_cast<uint8_t>(m.polePairs);
  // counts/cpr = dir·θm/2π + offset  →  θe/2π = pp·dir·(counts/cpr − offset)
  const double off = -m.polePairs * bc.encoderDirection * bc.encoderOffset;
  c.encoderOffset = static_cast<foc::Angle>(static_cast<int64_t>(std::ldexp(off - std::floor(off), 32)));
  const double r = m.resistance + b.motor().legResistance();
  c.inductanceD = static_cast<float>(m.inductanceD);
  c.inductanceQ = static_cast<float>(m.inductanceQ);
  c.fluxLinkage = static_cast<float>(m.fluxLinkage);
  c.currentGains = CurrentLoop::forMotor(static_cast<float>(r), static_cast<float>(m.inductanceQ), bandwidthHz);
  c.maxCurrent = 40.0f;
  c.overcurrentTrip = 60.0f;
  return c;
}

struct StepStats {
  float rise = 0.0f;       // s, 10–90 %
  float overshoot = 0.0f;  // fraction of the step
  float finalError = 0.0f; // fraction of the step, mean over the last 5 ms
  float peakCross = 0.0f;  // A, largest |id| during the step
};

// iq step from 0 to `amps` at t = 5 ms, 20 ms of record, on the motor's true currents.
StepStats currentStep(sim::Bench& b, foc::FocCore& core, float amps) {
  core.setAngleSource(foc::FocCore::AngleSource::Encoder);
  core.setDrive(foc::FocCore::Drive::Current);
  core.setCurrent({0.0f, 0.0f});
  const double T = b.config().pwmPeriod;
  const int start = static_cast<int>(0.005 / T), total = static_cast<int>(0.025 / T);
  std::vector<float> iq, id;
  for (int k = 0; k < total; ++k) {
    if (k == start) core.setCurrent({0.0f, amps});
    b.step(core.tick(b.sample()));
    if (k >= start) {
      iq.push_back(static_cast<float>(b.motor().iq()));
      id.push_back(static_cast<float>(b.motor().id()));
    }
  }
  StepStats s;
  int t10 = -1, t90 = -1;
  for (size_t k = 0; k < iq.size(); ++k) {
    if (t10 < 0 && iq[k] >= 0.1f * amps) t10 = static_cast<int>(k);
    if (t90 < 0 && iq[k] >= 0.9f * amps) t90 = static_cast<int>(k);
    s.overshoot = std::fmax(s.overshoot, (iq[k] - amps) / amps);
    s.peakCross = std::fmax(s.peakCross, std::fabs(id[k]));
  }
  s.rise = (t10 >= 0 && t90 >= 0) ? static_cast<float>((t90 - t10) * T) : 1.0f;
  const int tail = static_cast<int>(0.005 / T);
  double sum = 0.0;
  for (size_t k = iq.size() - tail; k < iq.size(); ++k) sum += iq[k];
  s.finalError = static_cast<float>(std::fabs(sum / tail - amps) / amps);
  return s;
}


// ---- calibration runs, shared by tests 4 and 5 (one ~15 s simulated run per motor) ----

struct Case {
  sim::MotorParams motor;
  sim::BenchConfig bench;
  float current;
};

std::vector<Case> cases() {
  std::vector<Case> out;
  sim::BenchConfig g;  // gimbal: high gain for its small currents; encoder mounted reversed
  g.csaGain = 40.0;
  g.encoderDirection = -1;
  g.encoderOffset = 0.71;
  g.seed = 11;
  out.push_back({sim::motors::gimbal(), g, 0.5f});
  sim::BenchConfig q;
  q.seed = 12;
  out.push_back({sim::motors::qdd5010(), q, 5.0f});
  sim::BenchConfig h;
  h.csaGain = 20.0;
  h.encoderDirection = -1;
  h.encoderOffset = 0.05;
  h.seed = 13;
  out.push_back({sim::motors::hobby2204(), h, 3.0f});
  return out;
}

struct CalibrationRun {
  Calibration::Result result;
  Calibration::Error error;
  double seconds;
};

// What the firmware knows before calibration: only the board (sense scales).
foc::FocCore::Config blankConfig(const sim::Bench& b) {
  foc::FocCore::Config c;
  c.tickPeriod = static_cast<float>(b.config().pwmPeriod);
  c.ampsPerCount = b.ampsPerCount();
  c.busVoltsPerCount = b.busVoltsPerCount();
  c.maxCurrent = 40.0f;
  c.overcurrentTrip = 60.0f;
  return c;
}

const std::vector<CalibrationRun>& calibrationRuns() {
  static std::vector<CalibrationRun> runs;
  if (!runs.empty()) return runs;
  for (const Case& k : cases()) {
    sim::Bench b(k.motor, k.bench);
    foc::FocCore core;
    core.configure(blankConfig(b));
    Calibration cal;
    Calibration::Settings s;
    s.current = k.current;
    cal.start(core, s);
    const int ticksPerMs = static_cast<int>(std::lround(1e-3 / b.config().pwmPeriod));
    while (cal.running() && b.time() < 60.0) {
      for (int i = 0; i < ticksPerMs; ++i) b.step(core.tick(b.sample()));
      cal.update(core);
    }
    runs.push_back({cal.result(), cal.error(), b.time()});
  }
  return runs;
}

double angleErrorDegrees(foc::Angle a, foc::Angle b) {
  return std::fabs(static_cast<double>(static_cast<int32_t>(a - b))) * 360.0 / 4294967296.0;
}
}  // namespace

// ---------------------------------------------------------------- 1. transforms and SVPWM

void test_clarke_park_reference_values() {
  for (int deg = 0; deg < 360; deg += 7) {
    const float th = static_cast<float>(deg * kTwoPi / 360.0);
    const foc::Abc x{std::cos(th), std::cos(th - 2.0943951f), std::cos(th + 2.0943951f)};
    const foc::AlphaBeta ab = foc::clarke(x);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, std::cos(th), ab.alpha);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, std::sin(th), ab.beta);
    float s, c;
    foc::sinCos(foc::fromRadians(th), s, c);
    const foc::Dq dq = foc::park(ab, s, c);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, 1.0f, dq.d);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, 0.0f, dq.q);
    const foc::Abc back = foc::inverseClarke(foc::inversePark(dq, s, c));
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, x.a, back.a);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, x.b, back.b);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, x.c, back.c);
  }
  // Binary angles wrap: three quarter turns forward is a quarter turn back.
  TEST_ASSERT_FLOAT_WITHIN(1e-6f, -1.5707963f, foc::toRadians(foc::fromRadians(4.712389f)));
}

void test_svpwm_reproduces_the_vector_and_never_leaves_the_linear_region() {
  const float vbus = 24.0f, limit = foc::linearLimit(vbus);
  for (int deg = 0; deg < 360; ++deg) {
    for (float m = 0.0f; m <= 1.3f; m += 0.05f) {
      const float th = static_cast<float>(deg * kTwoPi / 360.0);
      const foc::AlphaBeta v{m * limit * std::cos(th), m * limit * std::sin(th)};
      const foc::Duty3 d = foc::svpwm(v, vbus);
      TEST_ASSERT_TRUE(d.a >= 0.0f && d.a <= 1.0f && d.b >= 0.0f && d.b <= 1.0f && d.c >= 0.0f && d.c <= 1.0f);
      // What the floating neutral sees: the leg voltages minus their common mode.
      const float ua = d.a * vbus, ub = d.b * vbus, uc = d.c * vbus;
      const foc::AlphaBeta out = foc::clarke({ua, ub, uc});
      const float k = std::fmin(1.0f, 1.0f / std::fmax(m, 1e-6f));  // beyond the limit: scaled onto it
      TEST_ASSERT_FLOAT_WITHIN(2e-3f, v.alpha * k, out.alpha);
      TEST_ASSERT_FLOAT_WITHIN(2e-3f, v.beta * k, out.beta);
    }
  }
}

// ---------------------------------------------------------------- 2. current step

void test_current_step_meets_the_bandwidth_target() {
  sim::Bench b(sim::motors::qdd5010());
  b.motor().setMechanics(sim::Motor::Mechanics::Locked);
  b.motor().setAngle(0.37);
  foc::FocCore core;
  core.configure(knownMotor(b));
  const StepStats s = currentStep(b, core, 10.0f);
  // First order at 1.5 kHz: 2.2/ωc = 0.233 ms; allow the 1.5-period PWM delay on top.
  TEST_ASSERT_TRUE_MESSAGE(s.rise < 0.30e-3f, "10-90 % rise");
  TEST_ASSERT_TRUE_MESSAGE(s.overshoot < 0.05f, "overshoot");
  TEST_ASSERT_TRUE_MESSAGE(s.finalError < 0.01f, "steady-state error");
  TEST_ASSERT_EQUAL_UINT16(0, core.faults());
}

// ---------------------------------------------------------------- 3. decoupling at speed

void test_decoupling_keeps_id_flat_during_an_iq_step_at_half_base_speed() {
  const sim::MotorParams m = sim::motors::qdd5010();
  const double base = 24.0 / std::sqrt(3.0) * 0.95 / m.fluxLinkage;  // electrical rad/s
  const double omega = 0.5 * base / m.polePairs;                      // mechanical
  StepStats with, without;
  for (int pass = 0; pass < 2; ++pass) {
    sim::Bench b(m);
    b.motor().setMechanics(sim::Motor::Mechanics::Speed, omega);
    foc::FocCore core;
    foc::FocCore::Config c = knownMotor(b);
    c.decoupling = pass == 0;
    core.configure(c);
    // Let the tracker lock and the loop settle at speed before the step.
    core.setAngleSource(foc::FocCore::AngleSource::Encoder);
    core.setDrive(foc::FocCore::Drive::Current);
    for (int k = 0; k < 3000; ++k) b.step(core.tick(b.sample()));
    (pass == 0 ? with : without) = currentStep(b, core, 10.0f);
    TEST_ASSERT_EQUAL_UINT16(0, core.faults());
  }
  TEST_ASSERT_TRUE_MESSAGE(with.peakCross < 1.0f, "id excursion with decoupling (A)");
  TEST_ASSERT_TRUE_MESSAGE(with.rise < 0.35e-3f, "iq rise at speed");
  TEST_ASSERT_TRUE_MESSAGE(with.finalError < 0.02f, "iq steady-state error at speed");
  TEST_ASSERT_TRUE_MESSAGE(without.peakCross > 2.0f * with.peakCross, "decoupling makes a difference");
}


// ---------------------------------------------------------------- 6. position step and trajectory tracking

void test_joint_tracks_the_planner_and_settles() {
  sim::Bench b(sim::motors::qdd5010());
  Joint joint;
  Joint::Settings js;
  js.foc = knownMotor(b);
  js.foc.maxCurrent = 20.0f;
  // ωn = 2π·25 Hz on J = 6e-5 kg·m², ζ ≈ 0.8, in turns: kp = J·ωn²·2π, kd = 2ζ·ωn·J·2π.
  js.gains.kp = 9.3f;
  js.gains.kd = 0.095f;
  js.gains.ki = 60.0f;
  js.gains.integralLimit = 0.05f;
  js.commandTimeout = 0.0f;
  joint.configure(js);
  joint.setCalibrated(true);
  const int ticksPerMs = static_cast<int>(std::lround(1e-3 / b.config().pwmPeriod));
  const auto run = [&](double seconds, auto&& each) {
    for (int ms = 0; ms < static_cast<int>(seconds * 1000.0); ++ms) {
      for (int i = 0; i < ticksPerMs; ++i) b.step(joint.tick(b.sample()));
      Joint::SlowSample slow;
      slow.fetNtc = b.fetNtcCode();
      slow.driverFault = b.driverFault();
      joint.update(slow);
      each();
    }
  };
  run(0.05, [] {});
  TEST_ASSERT_TRUE(joint.enable());
  run(0.3, [] {});
  const double start = joint.telemetry().position;

  // A one-turn move at 10 turns/s and 100 turns/s².
  TEST_ASSERT_TRUE(joint.moveTo(start + 1.0, 10.0f, 100.0f));
  double worst = 0.0, overshoot = 0.0;
  run(0.6, [&] {
    const Joint::Telemetry t = joint.telemetry();
    worst = std::fmax(worst, std::fabs(t.target - t.position));
    overshoot = std::fmax(overshoot, t.position - (start + 1.0));
  });
  const Joint::Telemetry settled = joint.telemetry();
  TEST_ASSERT_EQUAL_INT(static_cast<int>(Joint::State::Holding), static_cast<int>(settled.state));
  TEST_ASSERT_TRUE_MESSAGE(worst < 0.01, "tracking error during the move");
  TEST_ASSERT_TRUE_MESSAGE(overshoot < 0.002, "overshoot");
  TEST_ASSERT_TRUE_MESSAGE(std::fabs(settled.position - (start + 1.0)) < 0.001, "final error");

  // Velocity mode: 5 turns/s.
  TEST_ASSERT_TRUE(joint.setVelocity(5.0f, 100.0f));
  run(0.5, [] {});
  float mean = 0.0f;
  run(0.2, [&] { mean += joint.telemetry().velocity / 200.0f; });
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 5.0f, mean);
  TEST_ASSERT_EQUAL_UINT16(0, joint.faults());
}

// ---------------------------------------------------------------- 4. pole pairs, direction, encoder offset

void test_calibration_finds_pole_pairs_direction_and_offset() {
  const std::vector<Case> cs = cases();
  const std::vector<CalibrationRun>& runs = calibrationRuns();
  for (size_t n = 0; n < cs.size(); ++n) {
    const Case& k = cs[n];
    const Calibration::Result& r = runs[n].result;
    printf("%-12s error %d  %.1f s  pp %d dir %d  spread %.4f\n", k.motor.name, static_cast<int>(runs[n].error),
           runs[n].seconds, r.polePairs, r.direction, r.offsetSpread);
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, static_cast<int>(runs[n].error), k.motor.name);
    TEST_ASSERT_EQUAL_INT_MESSAGE(k.motor.polePairs, r.polePairs, k.motor.name);
    TEST_ASSERT_EQUAL_INT_MESSAGE(k.bench.encoderDirection, r.direction, k.motor.name);
    const double off = -k.motor.polePairs * k.bench.encoderDirection * k.bench.encoderOffset;
    const foc::Angle truth = static_cast<foc::Angle>(static_cast<int64_t>(std::ldexp(off - std::floor(off), 32)));
    const double err = angleErrorDegrees(r.encoderOffset, truth);
    printf("%-12s offset error %.2f deg electrical\n", k.motor.name, err);
    TEST_ASSERT_TRUE_MESSAGE(err < 3.0, k.motor.name);
  }
}

// ---------------------------------------------------------------- 5. R, L, flux linkage

void test_identification_within_five_percent() {
  const std::vector<Case> cs = cases();
  const std::vector<CalibrationRun>& runs = calibrationRuns();
  for (size_t n = 0; n < cs.size(); ++n) {
    const Case& k = cs[n];
    const Calibration::Result& r = runs[n].result;
    const double rTrue = k.motor.resistance + k.bench.inverter.fetResistance + k.bench.inverter.shunt;
    printf("%-12s R %.4g (%.4g)  L %.4g (%.4g)  lambda %.4g (%.4g)\n", k.motor.name, r.resistance, rTrue,
           r.inductance, k.motor.inductanceD, r.fluxLinkage, k.motor.fluxLinkage);
    TEST_ASSERT_EQUAL_INT_MESSAGE(0, static_cast<int>(runs[n].error), k.motor.name);
    TEST_ASSERT_FLOAT_WITHIN_MESSAGE(0.05 * rTrue, rTrue, r.resistance, k.motor.name);
    TEST_ASSERT_FLOAT_WITHIN_MESSAGE(0.05 * k.motor.inductanceD, k.motor.inductanceD, r.inductance, k.motor.name);
    TEST_ASSERT_FLOAT_WITHIN_MESSAGE(0.05 * k.motor.fluxLinkage, k.motor.fluxLinkage, r.fluxLinkage, k.motor.name);
  }
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_clarke_park_reference_values);
  RUN_TEST(test_svpwm_reproduces_the_vector_and_never_leaves_the_linear_region);
  RUN_TEST(test_current_step_meets_the_bandwidth_target);
  RUN_TEST(test_decoupling_keeps_id_flat_during_an_iq_step_at_half_base_speed);
  RUN_TEST(test_calibration_finds_pole_pairs_direction_and_offset);
  RUN_TEST(test_identification_within_five_percent);
  RUN_TEST(test_joint_tracks_the_planner_and_settles);
  return UNITY_END();
}
