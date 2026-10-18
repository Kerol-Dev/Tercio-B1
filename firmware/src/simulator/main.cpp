// -----------------------------------------------------------------------------
// Tercio B1 simulator: the firmware's Joint (FocCore, calibration, outer
// loops, fault policy) running in real time against sim::Bench.
//
// Host only. Talks JSON lines: commands on stdin, telemetry on stdout. The
// web UI reaches it through firmware/simulator/server.mjs.
//
//   per PWM tick (30 kHz)   out = joint.tick(bench.sample()); bench.step(out)
//   per millisecond         joint.update(slow inputs); scope samples
//   per frame (~60 Hz wall) one "frame" message with the samples since the last
//
// Build: pio run -e simulator   (→ .pio/build/simulator/program)
// -----------------------------------------------------------------------------
#include <poll.h>
#include <unistd.h>

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "app/Joint.h"
#include "sim/Bench.h"

namespace {

constexpr double kTwoPi = 6.283185307179586;

// ---- Minimal JSON: flat objects in, hand-built strings out --------------------------------------------------

struct Message {
  std::map<std::string, std::string> s;
  std::map<std::string, double> n;
  std::string str(const std::string& k, const std::string& d = "") const {
    auto it = s.find(k);
    return it == s.end() ? d : it->second;
  }
  double num(const std::string& k, double d = 0.0) const {
    auto it = n.find(k);
    return it == n.end() ? d : it->second;
  }
  bool has(const std::string& k) const { return n.count(k) || s.count(k); }
};

Message parse(const std::string& line) {
  Message m;
  size_t i = 0;
  const auto skip = [&] { while (i < line.size() && (line[i] == ' ' || line[i] == '\t' || line[i] == ',' || line[i] == '{' || line[i] == '}')) ++i; };
  const auto readString = [&]() {
    std::string out;
    ++i;  // opening quote
    while (i < line.size() && line[i] != '"') {
      if (line[i] == '\\' && i + 1 < line.size()) ++i;
      out += line[i++];
    }
    ++i;
    return out;
  };
  while (true) {
    skip();
    if (i >= line.size() || line[i] != '"') break;
    const std::string key = readString();
    while (i < line.size() && (line[i] == ' ' || line[i] == ':')) ++i;
    if (i >= line.size()) break;
    if (line[i] == '"') {
      m.s[key] = readString();
    } else if (line.compare(i, 4, "true") == 0) {
      m.n[key] = 1.0;
      i += 4;
    } else if (line.compare(i, 5, "false") == 0) {
      m.n[key] = 0.0;
      i += 5;
    } else if (line.compare(i, 4, "null") == 0) {
      i += 4;
    } else {
      char* end = nullptr;
      m.n[key] = std::strtod(line.c_str() + i, &end);
      i = static_cast<size_t>(end - line.c_str());
    }
  }
  return m;
}

class Json {
 public:
  Json& key(const char* k) {
    sep();
    out_ += '"';
    out_ += k;
    out_ += "\":";
    fresh_ = true;
    return *this;
  }
  Json& num(double v, int digits = 6) {
    sep();
    if (!std::isfinite(v)) {
      out_ += "null";
    } else {
      char b[32];
      std::snprintf(b, sizeof b, "%.*g", digits, v);
      out_ += b;
    }
    return *this;
  }
  Json& str(const std::string& v) {
    sep();
    out_ += '"';
    for (char c : v) {
      if (c == '"' || c == '\\') out_ += '\\';
      out_ += c;
    }
    out_ += '"';
    return *this;
  }
  Json& boolean(bool v) {
    sep();
    out_ += v ? "true" : "false";
    return *this;
  }
  Json& open(char c = '{') {
    sep();
    out_ += c;
    fresh_ = true;
    return *this;
  }
  Json& close(char c = '}') {
    out_ += c;
    fresh_ = false;
    return *this;
  }
  Json& array(const char* k, const std::vector<float>& v, int digits = 5) {
    key(k).open('[');
    for (float x : v) num(x, digits);
    return close(']');
  }
  const std::string& text() const { return out_; }

 private:
  void sep() {
    if (!fresh_ && !out_.empty()) out_ += ',';
    fresh_ = false;
  }
  std::string out_;
  bool fresh_ = true;
};

void send(const Json& j) {
  std::fputs(j.text().c_str(), stdout);
  std::fputc('\n', stdout);
  std::fflush(stdout);
}

void event(const char* level, const std::string& text) {
  Json j;
  j.open().key("type").str("event").key("level").str(level).key("text").str(text).close();
  send(j);
}

// ---- Motor profiles: the bench (truth) and the defaults a user would start from ------------------------------

struct Profile {
  std::string id;
  sim::MotorParams motor;
  double csaGain;        // DRV8353 CSA gain the firmware selects for this motor
  float calCurrent;      // A
  float maxCurrent;      // A
  float maxVelocity;     // turns/s
  float maxAcceleration; // turns/s²
  float bandwidthHz;     // outer-loop tuning target
};

std::vector<Profile> profiles() {
  return {
      {"gimbal", sim::motors::gimbal(), 40.0, 0.5f, 1.5f, 10.0f, 200.0f, 15.0f},
      {"qdd5010", sim::motors::qdd5010(), 10.0, 5.0f, 30.0f, 30.0f, 400.0f, 25.0f},
      {"hobby2204", sim::motors::hobby2204(), 20.0, 3.0f, 15.0f, 80.0f, 1500.0f, 30.0f},
  };
}

// Outer-loop gains from the rotor inertia (what AutoTune will measure), in turns:
// kp = J·ωn²·2π, kd = 2ζ·ωn·J·2π, ζ = 0.8.
OuterLoop::Gains gainsFor(const Profile& p, double extraInertia) {
  const double j = p.motor.inertia + extraInertia;
  const double wn = kTwoPi * p.bandwidthHz;
  OuterLoop::Gains g;
  g.kp = static_cast<float>(j * wn * wn * kTwoPi);
  g.kd = static_cast<float>(2.0 * 0.8 * wn * j * kTwoPi);
  g.ki = g.kp * static_cast<float>(wn) * 0.1f;
  g.kv = g.kd * 2.0f;
  g.kvi = g.kv * static_cast<float>(wn) * 0.5f;
  g.integralLimit = static_cast<float>(p.motor.torqueConstant() * p.maxCurrent * 0.3);
  return g;
}

const char* stateName(Joint::State s) {
  switch (s) {
    case Joint::State::Disabled: return "Disabled";
    case Joint::State::Holding: return "Holding";
    case Joint::State::Moving: return "Moving";
    case Joint::State::Velocity: return "Velocity";
    case Joint::State::Calibrating: return "Calibrating";
    case Joint::State::Fault: return "Fault";
    case Joint::State::Torque: return "Torque";
    case Joint::State::Impedance: return "Impedance";
  }
  return "?";
}

const char* phaseName(Calibration::Phase p) {
  switch (p) {
    case Calibration::Phase::Idle: return "idle";
    case Calibration::Phase::Offsets: return "offsets";
    case Calibration::Phase::Resistance: return "resistance";
    case Calibration::Phase::Inductance: return "inductance";
    case Calibration::Phase::PolePairs: return "polePairs";
    case Calibration::Phase::EncoderOffset: return "encoderOffset";
    case Calibration::Phase::FluxLinkage: return "fluxLinkage";
    case Calibration::Phase::Done: return "done";
    case Calibration::Phase::Failed: return "failed";
  }
  return "?";
}

const char* errorName(Calibration::Error e) {
  switch (e) {
    case Calibration::Error::None: return "none";
    case Calibration::Error::Fault: return "a fault was latched";
    case Calibration::Error::Aborted: return "aborted";
    case Calibration::Error::NoCurrent: return "no current at the voltage limit (open phase or R too high)";
    case Calibration::Error::Resistance: return "resistance out of range";
    case Calibration::Error::Inductance: return "inductance out of range";
    case Calibration::Error::NoMotion: return "the encoder did not move with the field";
    case Calibration::Error::PolePairs: return "pole pairs did not come out whole";
    case Calibration::Error::EncoderNoise: return "encoder offset samples disagree";
    case Calibration::Error::Flux: return "the motor did not reach speed for the flux test";
  }
  return "?";
}

// ---- The simulated world -------------------------------------------------------------------------------------

class World {
 public:
  World() { load("qdd5010"); }

  void load(const std::string& id) {
    for (const Profile& p : profiles()) {
      if (p.id == id) profile_ = p;
    }
    if (profile_.id.empty()) profile_ = profiles()[1];
    sim::BenchConfig bc;
    bc.csaGain = profile_.csaGain;
    bc.supply = supply_;
    bc.thermal = thermal_;
    bc.vdsLevel = vdsLevel_;
    bc.substeps = 16;
    bc.seed = static_cast<uint32_t>(std::rand());
    // How the magnet sits on this motor's shaft: unknown to the firmware, fixed per motor, so a
    // stored calibration stays valid when the motor is selected again.
    if (!mount_.count(profile_.id)) mount_[profile_.id] = {std::fmod(0.137 + (std::rand() % 1000) / 1000.0, 1.0), std::rand() % 2 ? 1 : -1};
    bc.encoderOffset = mount_[profile_.id].offset;
    bc.encoderDirection = mount_[profile_.id].direction;
    bench_ = std::make_unique<sim::Bench>(profile_.motor, bc);
    bench_->motor().setExtraInertia(extraInertia_);
    bench_->motor().setBrake(brake_);
    bench_->motor().setLoad(load_);

    Joint::Settings js;
    js.foc.tickPeriod = static_cast<float>(bc.pwmPeriod);
    js.foc.ampsPerCount = bench_->ampsPerCount();
    js.foc.busVoltsPerCount = bench_->busVoltsPerCount();
    js.foc.maxCurrent = profile_.maxCurrent;
    js.foc.overcurrentTrip = profile_.maxCurrent * 1.6f + 2.0f;
    js.gains = gainsFor(profile_, extraInertia_);
    js.maxVelocity = profile_.maxVelocity;
    js.maxAcceleration = profile_.maxAcceleration;
    js.motorNtc = true;
    joint_.configure(js);
    // A calibration stored "in flash" for this motor survives a reload, as on the real board.
    auto stored = flash_.find(profile_.id);
    if (stored != flash_.end()) {
      foc::FocCore::Config c = stored->second;
      c.ampsPerCount = js.foc.ampsPerCount;
      c.busVoltsPerCount = js.foc.busVoltsPerCount;
      c.maxCurrent = js.foc.maxCurrent;
      c.overcurrentTrip = js.foc.overcurrentTrip;
      joint_.settings().foc = c;
      joint_.configure(joint_.settings());
      joint_.setCalibrated(true);
    }
    capture_.clear();
    captureLeft_ = 0;
    info();
  }

  void info() {
    const sim::MotorParams& m = profile_.motor;
    Json j;
    j.open().key("type").str("info");
    j.key("motor").open().key("id").str(profile_.id).key("name").str(m.name).key("R").num(m.resistance).key("L").num(m.inductanceD)
        .key("lambda").num(m.fluxLinkage).key("pp").num(m.polePairs).key("J").num(m.inertia).key("Kt").num(m.torqueConstant())
        .key("Kv").num(60.0 / (kTwoPi * std::sqrt(3.0) * m.polePairs * m.fluxLinkage), 4)
        .key("ratedCurrent").num(m.ratedCurrent).key("coulomb").num(m.coulomb).close();
    j.key("profile").open().key("calCurrent").num(profile_.calCurrent).key("maxCurrent").num(profile_.maxCurrent)
        .key("maxVelocity").num(profile_.maxVelocity).key("maxAcceleration").num(profile_.maxAcceleration)
        .key("csaGain").num(profile_.csaGain).key("ampsPerCount").num(bench_->ampsPerCount())
        .key("maxTorque").num(m.torqueConstant() * profile_.maxCurrent).close();
    const OuterLoop::Gains& g = joint_.settings().gains;
    j.key("gains").open().key("kp").num(g.kp).key("kd").num(g.kd).key("ki").num(g.ki).key("kv").num(g.kv).key("kvi").num(g.kvi).close();
    j.key("supply").open().key("kind").str(supply_.kind == sim::SupplyParams::Kind::Bench ? "bench" : "battery")
        .key("volts").num(supply_.volts).key("limit").num(supply_.currentLimit).key("connected").boolean(supply_.connected).close();
    j.key("profiles").open('[');
    for (const Profile& q : profiles()) {
      const sim::MotorParams& pm = q.motor;
      j.open().key("id").str(q.id).key("name").str(pm.name).key("R").num(pm.resistance).key("L").num(pm.inductanceD)
          .key("pp").num(pm.polePairs).key("Kv").num(60.0 / (kTwoPi * std::sqrt(3.0) * pm.polePairs * pm.fluxLinkage), 3)
          .key("Kt").num(pm.torqueConstant()).key("maxCurrent").num(q.maxCurrent).key("stored").boolean(flash_.count(q.id) > 0).close();
    }
    j.close(']');
    j.key("calibrated").boolean(joint_.calibrated());
    j.key("timeout").num(joint_.settings().commandTimeout);
    j.key("vdsLevel").num(vdsLevel_);
    j.key("ambient").num(thermal_.ambient).key("cooling").num(thermal_.boardResistance);
    j.close();
    send(j);
  }

  // One millisecond of firmware time.
  void stepMs() {
    const int ticks = 30;
    Average sum{};
    for (int k = 0; k < ticks; ++k) {
      const foc::Sample s = bench_->sample();
      const foc::Output out = joint_.tick(s);
      bench_->step(out);
      if (captureLeft_ > 0) recordCapture(out);
      const foc::FocCore& core = joint_.core();
      sum.id += core.current().d;
      sum.iq += core.current().q;
      sum.vd += core.voltage().d;
      sum.vq += core.voltage().q;
    }
    // What a 1 kHz telemetry logger reports: means over the millisecond, not one noisy tick.
    const float k = 1.0f / ticks;
    ms_ = {sum.id * k, sum.iq * k, sum.vd * k, sum.vq * k};
    applyHand();
    Joint::SlowSample slow;
    slow.fetNtc = bench_->fetNtcCode();
    slow.motorNtc = bench_->motorNtcCode();
    slow.driverFault = bench_->driverFault();
    const Joint::State before = joint_.state();
    const Calibration::Phase phaseBefore = joint_.calibration().phase();
    const uint16_t faultsBefore = joint_.faults();
    joint_.update(slow);
    report(before, phaseBefore, faultsBefore);
    sampleSeries();
  }

  void report(Joint::State before, Calibration::Phase phaseBefore, uint16_t faultsBefore) {
    const Calibration& cal = joint_.calibration();
    if (cal.phase() != phaseBefore) {
      if (cal.phase() == Calibration::Phase::Done) {
        storeCalibration();
        calibrationResult();
        event("good", "Calibration finished and stored.");
        info();
      } else if (cal.phase() == Calibration::Phase::Failed) {
        event("bad", std::string("Calibration failed: ") + errorName(cal.error()) + ".");
        calibrationResult();
      } else {
        calibrationResult();
      }
    }
    const uint16_t f = joint_.faults();
    if (f != faultsBefore && f) {
      static const char* names[16] = {"FET over-temperature", "", "Driver fault (nFAULT)", "", "Encoder lost", "", "Calibration failed",
                                      "", "Command timeout", "Bus over-voltage", "Bus under-voltage", "Phase over-current",
                                      "Motor over-temperature", "", "", ""};
      for (int b = 0; b < 16; ++b) {
        if ((f & ~faultsBefore) & (1u << b)) event((Joint::Fault::kHardMask & (1u << b)) ? "bad" : "warn", std::string(names[b]) + ".");
      }
    }
    if (joint_.state() != before && joint_.state() == Joint::State::Fault) event("bad", "Bridge off: hard fault latched.");
  }

  void storeCalibration() { flash_[profile_.id] = joint_.core().config(); }

  void calibrationResult() {
    const Calibration& cal = joint_.calibration();
    const Calibration::Result& r = cal.result();
    const sim::MotorParams& m = profile_.motor;
    const sim::BenchConfig& bc = bench_->config();
    // The truth the calibration should find (resistance includes the bridge and today's temperatures).
    const double off = -m.polePairs * bc.encoderDirection * bc.encoderOffset;
    const double offTrue = (off - std::floor(off)) * 360.0;
    Json j;
    j.open().key("type").str("calibration").key("phase").str(phaseName(cal.phase()))
        .key("error").str(cal.phase() == Calibration::Phase::Failed ? errorName(cal.error()) : "");
    j.key("found").open().key("offsets").open('[').num(r.offset[0]).num(r.offset[1]).num(r.offset[2]).close(']')
        .key("R").num(r.resistance).key("L").num(r.inductance).key("pp").num(r.polePairs).key("dir").num(r.direction)
        .key("offset").num(static_cast<double>(r.encoderOffset) * 360.0 / 4294967296.0).key("lambda").num(r.fluxLinkage)
        .key("Kt").num(r.torqueConstant()).close();
    j.key("truth").open().key("R").num(bench_->motor().resistance() + bench_->motor().legResistance()).key("L").num(m.inductanceD)
        .key("pp").num(m.polePairs).key("dir").num(bc.encoderDirection).key("offset").num(offTrue).key("lambda").num(m.fluxLinkage)
        .key("Kt").num(m.torqueConstant()).close();
    j.close();
    send(j);
  }

  // ---- Scope -------------------------------------------------------------------------------------------------
  struct Series {
    std::vector<float> t, pos, target, vel, tvel, iq, iqref, id, vd, vq, vbus, ibus, isup, torque, ttrue, tfet, tmot;
    void clear() {
      for (auto* v : {&t, &pos, &target, &vel, &tvel, &iq, &iqref, &id, &vd, &vq, &vbus, &ibus, &isup, &torque, &ttrue, &tfet, &tmot}) v->clear();
    }
  } series_;

  struct Average {
    float id, iq, vd, vq;
  } ms_{0, 0, 0, 0};

  float busEstimate(float vbus) const { return vbus > 1.0f ? 1.5f * (ms_.vd * ms_.id + ms_.vq * ms_.iq) / vbus : 0.0f; }

  void sampleSeries() {
    const Joint::Telemetry t = joint_.telemetry();
    const sim::Motor& m = bench_->motor();
    const float kt = joint_.torqueConstant();
    series_.t.push_back(static_cast<float>(bench_->time()));
    series_.pos.push_back(static_cast<float>(t.position));
    series_.target.push_back(static_cast<float>(t.target));
    series_.vel.push_back(t.velocity);
    series_.tvel.push_back(t.targetVelocity);
    series_.iq.push_back(ms_.iq);
    series_.iqref.push_back(t.idqRef.q);
    series_.id.push_back(ms_.id);
    series_.vd.push_back(ms_.vd);
    series_.vq.push_back(ms_.vq);
    series_.vbus.push_back(static_cast<float>(m.busVoltage()));
    series_.ibus.push_back(busEstimate(t.vbus));
    series_.isup.push_back(static_cast<float>(m.supplyCurrent()));
    series_.torque.push_back(kt * ms_.iq);
    series_.ttrue.push_back(static_cast<float>(m.torque()));
    series_.tfet.push_back(static_cast<float>(m.boardTemperature()));
    series_.tmot.push_back(static_cast<float>(m.motorTemperature()));
  }

  void frame(double realtime) {
    const Joint::Telemetry t = joint_.telemetry();
    const sim::Motor& m = bench_->motor();
    const foc::FocCore& core = joint_.core();
    Json j;
    j.open().key("type").str("frame").key("time").num(bench_->time(), 9).key("realtime").num(realtime, 3)
        .key("paused").boolean(paused_).key("speed").num(speed_);
    j.key("state").str(stateName(t.state)).key("faults").num(t.faults).key("warnings").num(t.warnings)
        .key("calibrated").boolean(joint_.calibrated()).key("calPhase").str(phaseName(t.calibration));
    j.key("pos").num(t.position, 9).key("vel").num(t.velocity).key("target").num(t.target, 9).key("tvel").num(t.targetVelocity)
        .key("torque").num(joint_.torqueConstant() * ms_.iq).key("torqueRef").num(t.torqueRef).key("id").num(ms_.id)
        .key("iq").num(ms_.iq).key("iqRef").num(t.idqRef.q).key("vd").num(ms_.vd).key("vq").num(ms_.vq).key("vbus").num(t.vbus)
        .key("ibus").num(busEstimate(t.vbus))
        .key("tfet").num(t.fetTemperature, 4).key("tmot").num(t.motorTemperature, 4).key("derate").num(t.derate, 3)
        .key("elec").num(foc::toRadians(core.angle()), 5);
    double i[3];
    m.phaseCurrents(i);
    const double* d = bench_->duties();
    j.key("truth").open().key("angle").num(m.angle(), 9).key("omega").num(m.velocity()).key("torque").num(m.torque())
        .key("vbus").num(m.busVoltage()).key("isup").num(m.supplyCurrent()).key("tboard").num(m.boardTemperature(), 4)
        .key("tmotor").num(m.motorTemperature(), 4).key("R").num(m.resistance()).key("loss").num(m.lossPower())
        .key("ia").num(i[0]).key("ib").num(i[1]).key("ic").num(i[2]).key("bridge").boolean(bench_->bridgeEnabled())
        .key("driverFault").boolean(bench_->driverFault()).key("magnet").boolean(bench_->magnet())
        .key("duty").open('[').num(d[0], 4).num(d[1], 4).num(d[2], 4).close(']')
        .key("load").num(handTorque_ + load_).key("locked").boolean(m.mechanics() == sim::Motor::Mechanics::Locked).close();
    j.key("series").open();
    j.array("t", series_.t, 9).array("pos", series_.pos, 7).array("target", series_.target, 7).array("vel", series_.vel)
        .array("tvel", series_.tvel).array("iq", series_.iq).array("iqRef", series_.iqref).array("id", series_.id)
        .array("vd", series_.vd).array("vq", series_.vq).array("vbus", series_.vbus).array("ibus", series_.ibus)
        .array("isup", series_.isup).array("torque", series_.torque).array("torqueTrue", series_.ttrue)
        .array("tfet", series_.tfet, 4).array("tmot", series_.tmot, 4);
    j.close().close();
    send(j);
    series_.clear();
  }

  // ---- 30 kHz capture: every tick of a short window ----------------------------------------------------------
  struct CaptureRow {
    float ia, ib, ic, ma, mb, mc, id, iq, iqref, vd, vq, da, db, dc, elec;
  };
  std::vector<CaptureRow> capture_;
  int captureLeft_ = 0;

  void startCapture(double ms) {
    capture_.clear();
    captureLeft_ = static_cast<int>(std::fmin(std::fmax(ms, 1.0), 200.0) * 30.0);
  }

  void recordCapture(const foc::Output& out) {
    const foc::FocCore& core = joint_.core();
    double i[3];
    bench_->motor().phaseCurrents(i);
    const foc::Abc mi = core.phaseCurrents();
    const Joint::Telemetry t = joint_.telemetry();
    capture_.push_back({static_cast<float>(i[0]), static_cast<float>(i[1]), static_cast<float>(i[2]), mi.a, mi.b, mi.c,
                        core.current().d, core.current().q, t.idqRef.q, core.voltage().d, core.voltage().q,
                        out.enable ? out.duty.a : 0.5f, out.enable ? out.duty.b : 0.5f, out.enable ? out.duty.c : 0.5f,
                        foc::toRadians(core.angle())});
    if (--captureLeft_ == 0) sendCapture();
  }

  void sendCapture() {
    Json j;
    j.open().key("type").str("capture").key("dt").num(bench_->config().pwmPeriod);
    const auto col = [&](const char* k, float CaptureRow::*f) {
      std::vector<float> v;
      v.reserve(capture_.size());
      for (const CaptureRow& r : capture_) v.push_back(r.*f);
      j.array(k, v, 5);
    };
    col("ia", &CaptureRow::ia);
    col("ib", &CaptureRow::ib);
    col("ic", &CaptureRow::ic);
    col("ma", &CaptureRow::ma);
    col("mb", &CaptureRow::mb);
    col("mc", &CaptureRow::mc);
    col("id", &CaptureRow::id);
    col("iq", &CaptureRow::iq);
    col("iqRef", &CaptureRow::iqref);
    col("vd", &CaptureRow::vd);
    col("vq", &CaptureRow::vq);
    col("da", &CaptureRow::da);
    col("db", &CaptureRow::db);
    col("dc", &CaptureRow::dc);
    col("elec", &CaptureRow::elec);
    j.close();
    send(j);
    capture_.clear();
  }

  // ---- The user's hand on the rotor: a stiff, damped spring to where the pointer holds it ------------------
  void applyHand() {
    sim::Motor& m = bench_->motor();
    if (handActive_) {
      const double j = profile_.motor.inertia + extraInertia_;
      const double wn = kTwoPi * 8.0;  // a hand is stiff but not infinitely
      const double k = j * wn * wn + profile_.motor.torqueConstant() * profile_.maxCurrent * 2.0;
      double err = handAngle_ - m.angle();
      handTorque_ = std::clamp(-(k * err - 2.0 * 0.7 * std::sqrt(k * j) * m.velocity()),
                               -3.0 * profile_.motor.torqueConstant() * profile_.maxCurrent,
                               3.0 * profile_.motor.torqueConstant() * profile_.maxCurrent);
    } else {
      handTorque_ = 0.0;
    }
    m.setLoad(load_ + handTorque_);
  }

  // ---- Commands ----------------------------------------------------------------------------------------------
  void command(const Message& c) {
    const std::string cmd = c.str("cmd");
    const auto refuse = [&](bool ok, const char* what) {
      if (!ok) event("warn", std::string(what) + " refused in state " + stateName(joint_.state()) +
                                 (joint_.calibrated() ? "." : " (not calibrated)."));
    };
    if (cmd == "heartbeat") {
      joint_.heartbeat();
    } else if (cmd == "enable") {
      refuse(joint_.enable(), "Enable");
    } else if (cmd == "disable") {
      joint_.disable();
    } else if (cmd == "stop") {
      joint_.stop();
    } else if (cmd == "clear") {
      bench_->clearDriverFault();
      joint_.clearFaults();
      event("info", "Faults cleared.");
    } else if (cmd == "calibrate") {
      Calibration::Settings s;
      s.current = static_cast<float>(c.num("current", profile_.calCurrent));
      if (joint_.state() != Joint::State::Disabled) joint_.disable();
      refuse(joint_.calibrate(s), "Calibrate");
      if (joint_.state() == Joint::State::Calibrating) event("info", "Calibrating at " + fmt(s.current) + " A.");
    } else if (cmd == "move") {
      refuse(joint_.moveTo(c.num("position"), static_cast<float>(c.num("velocity", profile_.maxVelocity * 0.5)),
                           static_cast<float>(c.num("accel", profile_.maxAcceleration * 0.5))), "Move");
    } else if (cmd == "velocity") {
      refuse(joint_.setVelocity(static_cast<float>(c.num("value")), static_cast<float>(c.num("accel", profile_.maxAcceleration * 0.5))),
             "Velocity");
    } else if (cmd == "torque") {
      refuse(joint_.setTorque(static_cast<float>(c.num("value")), static_cast<float>(c.num("maxVelocity", profile_.maxVelocity))), "Torque");
    } else if (cmd == "impedance") {
      refuse(joint_.impedance(c.num("position"), static_cast<float>(c.num("velocity")), static_cast<float>(c.num("kp")),
                              static_cast<float>(c.num("kd")), static_cast<float>(c.num("torque"))), "Impedance");
    } else if (cmd == "gains") {
      OuterLoop::Gains g = joint_.settings().gains;
      g.kp = static_cast<float>(c.num("kp", g.kp));
      g.kd = static_cast<float>(c.num("kd", g.kd));
      g.ki = static_cast<float>(c.num("ki", g.ki));
      g.kv = static_cast<float>(c.num("kv", g.kv));
      g.kvi = static_cast<float>(c.num("kvi", g.kvi));
      joint_.setGains(g);
    } else if (cmd == "timeout") {
      joint_.settings().commandTimeout = static_cast<float>(c.num("seconds", 1.0));
    } else if (cmd == "motor") {
      load(c.str("id", profile_.id));
      event("info", std::string("Motor: ") + profile_.motor.name + (joint_.calibrated() ? " (stored calibration loaded)." : ", not calibrated yet."));
    } else if (cmd == "supply") {
      if (c.has("kind")) supply_.kind = c.str("kind") == "battery" ? sim::SupplyParams::Kind::Battery : sim::SupplyParams::Kind::Bench;
      supply_.volts = c.num("volts", supply_.volts);
      supply_.currentLimit = c.num("limit", supply_.currentLimit);
      if (c.has("connected")) supply_.connected = c.num("connected") != 0.0;
      bench_->motor().supply() = supply_;
      info();
    } else if (cmd == "load") {
      if (c.has("torque")) load_ = c.num("torque");
      if (c.has("brake")) bench_->motor().setBrake(brake_ = c.num("brake"));
      if (c.has("inertia")) {
        extraInertia_ = c.num("inertia");
        bench_->motor().setExtraInertia(extraInertia_);
      }
      if (c.has("locked")) bench_->motor().setMechanics(c.num("locked") != 0.0 ? sim::Motor::Mechanics::Locked : sim::Motor::Mechanics::Free);
    } else if (cmd == "hand") {
      handActive_ = c.num("active") != 0.0;
      if (c.has("angle")) handAngle_ = c.num("angle");
    } else if (cmd == "environment") {
      thermal_.ambient = c.num("ambient", thermal_.ambient);
      thermal_.boardResistance = c.num("cooling", thermal_.boardResistance);
      bench_->motor().thermal() = thermal_;
    } else if (cmd == "magnet") {
      bench_->setMagnet(c.num("present", 1.0) != 0.0);
      event(bench_->magnet() ? "info" : "warn", bench_->magnet() ? "Magnet back on the shaft." : "Magnet removed from the shaft.");
    } else if (cmd == "slip") {
      bench_->slipEncoder(c.num("turns", 0.02));
      mount_[profile_.id].offset = bench_->config().encoderOffset;
      event("warn", "Magnet slipped on the shaft by " + fmt(c.num("turns", 0.02) * 360.0) + "° (the stored offset is now wrong).");
    } else if (cmd == "vds") {
      vdsLevel_ = c.num("volts", vdsLevel_);
      bench_->config().vdsLevel = vdsLevel_;
      event("info", "DRV8353 VDS_LVL = " + fmt(vdsLevel_) + " V (trips at " + fmt(vdsLevel_ / 3e-3) + " A per FET at 25 °C).");
    } else if (cmd == "speed") {
      speed_ = std::clamp(c.num("value", 1.0), 0.01, 100.0);
    } else if (cmd == "pause") {
      paused_ = c.num("value", paused_ ? 0.0 : 1.0) != 0.0;
    } else if (cmd == "capture") {
      startCapture(c.num("ms", 20.0));
    } else if (cmd == "forget") {
      flash_.erase(profile_.id);
      load(profile_.id);
      event("info", "Stored calibration erased.");
    } else if (cmd == "info") {
      info();
    }
  }

  static std::string fmt(double v) {
    char b[32];
    std::snprintf(b, sizeof b, "%.3g", v);
    return b;
  }

  bool paused() const { return paused_; }
  double speed() const { return speed_; }
  double time() const { return bench_->time(); }

 private:
  Profile profile_;
  std::unique_ptr<sim::Bench> bench_;
  Joint joint_;
  sim::SupplyParams supply_{};
  sim::ThermalParams thermal_{};
  double vdsLevel_ = 0.6;
  double load_ = 0.0, brake_ = 0.0, extraInertia_ = 0.0;
  bool handActive_ = false;
  double handAngle_ = 0.0, handTorque_ = 0.0;
  bool paused_ = false;
  double speed_ = 1.0;
  std::map<std::string, foc::FocCore::Config> flash_;
  struct Mount {
    double offset;
    int direction;
  };
  std::map<std::string, Mount> mount_;
};

}  // namespace

int main() {
  std::srand(static_cast<unsigned>(std::chrono::steady_clock::now().time_since_epoch().count()));
  World world;
  using Clock = std::chrono::steady_clock;
  const auto frameEvery = std::chrono::microseconds(16667);
  auto nextFrame = Clock::now() + frameEvery;
  auto anchorWall = Clock::now();
  double anchorSim = world.time();
  double anchorSpeed = world.speed();
  bool anchorPaused = world.paused();
  double lastSim = world.time();
  auto lastWall = Clock::now();
  std::string buffer;

  event("info", "Simulator ready: firmware Joint + FocCore on a simulated bench, 30 kHz PWM.");
  while (true) {
    // Commands (non-blocking).
    pollfd p{0, POLLIN, 0};
    while (poll(&p, 1, 0) > 0 && (p.revents & (POLLIN | POLLHUP))) {
      char chunk[4096];
      const ssize_t n = read(0, chunk, sizeof chunk);
      if (n <= 0) return 0;  // the server went away
      buffer.append(chunk, static_cast<size_t>(n));
      size_t nl;
      while ((nl = buffer.find('\n')) != std::string::npos) {
        const std::string line = buffer.substr(0, nl);
        buffer.erase(0, nl + 1);
        if (!line.empty()) world.command(parse(line));
      }
    }
    const auto now = Clock::now();
    if (world.speed() != anchorSpeed || world.paused() != anchorPaused) {
      anchorWall = now;
      anchorSim = world.time();
      anchorSpeed = world.speed();
      anchorPaused = world.paused();
    }
    if (!world.paused()) {
      const double wall = std::chrono::duration<double>(now - anchorWall).count();
      const double target = anchorSim + wall * world.speed();
      // Catch up in slices so frames keep flowing; if the host cannot keep up, drop the backlog.
      const auto budget = now + std::chrono::milliseconds(12);
      while (world.time() + 0.0005 < target && Clock::now() < budget) world.stepMs();
      if (target - world.time() > 0.1) {
        anchorWall = Clock::now();
        anchorSim = world.time();
      }
    }
    if (Clock::now() >= nextFrame) {
      const auto wallNow = Clock::now();
      const double dw = std::chrono::duration<double>(wallNow - lastWall).count();
      const double rt = dw > 0.0 ? (world.time() - lastSim) / dw : 0.0;
      lastWall = wallNow;
      lastSim = world.time();
      world.frame(rt);
      nextFrame += frameEvery;
      if (nextFrame < Clock::now()) nextFrame = Clock::now() + frameEvery;
    }
    std::this_thread::sleep_until(std::min(nextFrame, Clock::now() + std::chrono::milliseconds(2)));
  }
}
