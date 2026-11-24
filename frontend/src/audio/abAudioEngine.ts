/**
 * Sample-synchronized Web Audio API playback engine for click-free A/B,
 * live Dry/Wet blending, and Processing Difference (Residual) auditioning.
 */

export type CompareListenMode = "original" | "processed" | "mix" | "residual";

export interface AbAudioState {
  ready: boolean;
  loading: boolean;
  playing: boolean;
  currentTime: number;
  duration: number;
  error: string | null;
}

type StateListener = (state: AbAudioState) => void;

const CROSSFADE_SECONDS = 0.012;

function getAudioContextConstructor(): typeof AudioContext | null {
  if (typeof window === "undefined") return null;
  const ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  return ctor ?? null;
}

export class AbAudioEngine {
  private ctx: AudioContext | null = null;
  private originalBuffer: AudioBuffer | null = null;
  private processedBuffer: AudioBuffer | null = null;
  private residualBuffer: AudioBuffer | null = null;

  private origSource: AudioBufferSourceNode | null = null;
  private procSource: AudioBufferSourceNode | null = null;
  private resSource: AudioBufferSourceNode | null = null;

  private origGain: GainNode | null = null;
  private procGain: GainNode | null = null;
  private resGain: GainNode | null = null;
  private masterGain: GainNode | null = null;

  private mode: CompareListenMode = "processed";
  private wetMix = 1.0;
  private volume = 1.0;
  private muted = false;

  private playing = false;
  private startCtxTime = 0;
  private offsetSec = 0;
  private durationSec = 0;
  private rafId: number | null = null;
  private loadToken = 0;
  private disposed = false;

  private readonly listener: StateListener;

  constructor(listener: StateListener) {
    this.listener = listener;
  }

  private emit(partial: Partial<AbAudioState> = {}): void {
    if (this.disposed) return;
    this.listener({
      ready: this.originalBuffer !== null && this.processedBuffer !== null,
      loading: false,
      playing: this.playing,
      currentTime: this.getCurrentTime(),
      duration: this.durationSec,
      error: null,
      ...partial,
    });
  }

  private ensureContext(): AudioContext {
    if (!this.ctx) {
      const Ctor = getAudioContextConstructor();
      if (!Ctor) {
        throw new Error("Web Audio API is not available in this browser.");
      }
      this.ctx = new Ctor();
      this.origGain = this.ctx.createGain();
      this.procGain = this.ctx.createGain();
      this.resGain = this.ctx.createGain();
      this.masterGain = this.ctx.createGain();

      this.origGain.connect(this.masterGain);
      this.procGain.connect(this.masterGain);
      this.resGain.connect(this.masterGain);
      this.masterGain.connect(this.ctx.destination);
      this.applyGains(false);
    }
    return this.ctx;
  }

  async load(
    originalUrl: string,
    processedUrl: string,
    residualUrl: string,
    fallbackDurationSec: number,
  ): Promise<void> {
    const token = ++this.loadToken;
    this.stopSources();
    this.playing = false;
    this.offsetSec = 0;
    this.durationSec = fallbackDurationSec;
    this.originalBuffer = null;
    this.processedBuffer = null;
    this.residualBuffer = null;

    this.emit({ ready: false, loading: true, error: null });

    try {
      const ctx = this.ensureContext();
      const [origRes, procRes, resRes] = await Promise.all([
        fetch(originalUrl, { cache: "no-store" }),
        fetch(processedUrl, { cache: "no-store" }),
        fetch(residualUrl, { cache: "no-store" }),
      ]);

      if (!origRes.ok || !procRes.ok || !resRes.ok) {
        throw new Error(
          `Failed to stream audio for comparison (HTTP ${origRes.status}/${procRes.status}/${resRes.status}).`,
        );
      }

      const [origArr, procArr, resArr] = await Promise.all([
        origRes.arrayBuffer(),
        procRes.arrayBuffer(),
        resRes.arrayBuffer(),
      ]);

      const [origBuf, procBuf, resBuf] = await Promise.all([
        ctx.decodeAudioData(origArr),
        ctx.decodeAudioData(procArr),
        ctx.decodeAudioData(resArr),
      ]);

      if (this.disposed || token !== this.loadToken) {
        return;
      }

      this.originalBuffer = origBuf;
      this.processedBuffer = procBuf;
      this.residualBuffer = resBuf;
      this.durationSec = Math.min(origBuf.duration, procBuf.duration);
      this.applyGains(false);
      this.emit({ ready: true, loading: false, error: null });
    } catch (err) {
      if (this.disposed || token !== this.loadToken) {
        return;
      }
      const message =
        err instanceof Error
          ? err.message
          : "Unable to decode audio buffers for A/B playback.";
      this.emit({ ready: false, loading: false, playing: false, error: message });
    }
  }

  private getCurrentTime(): number {
    if (!this.playing || !this.ctx) {
      return Math.min(this.durationSec, Math.max(0, this.offsetSec));
    }
    const elapsed = this.ctx.currentTime - this.startCtxTime;
    return Math.min(this.durationSec, Math.max(0, this.offsetSec + elapsed));
  }

  private stopSources(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    for (const src of [this.origSource, this.procSource, this.resSource]) {
      if (src) {
        try {
          src.onended = null;
          src.stop();
          src.disconnect();
        } catch {
          // Source may already be stopped
        }
      }
    }
    this.origSource = null;
    this.procSource = null;
    this.resSource = null;
  }

  private applyGains(smooth: boolean): void {
    if (!this.ctx || !this.origGain || !this.procGain || !this.resGain || !this.masterGain) {
      return;
    }
    const now = this.ctx.currentTime;

    let gOrig = 0;
    let gProc = 0;
    let gRes = 0;

    if (this.mode === "original") {
      gOrig = 1;
    } else if (this.mode === "processed") {
      gProc = 1;
    } else if (this.mode === "mix") {
      gProc = Math.min(1, Math.max(0, this.wetMix));
      gOrig = 1 - gProc;
    } else if (this.mode === "residual") {
      gRes = 1;
    }

    const master = this.muted ? 0 : Math.min(1, Math.max(0, this.volume));

    const ramp = (param: AudioParam, target: number) => {
      if (smooth) {
        if (typeof param.cancelAndHoldAtTime === "function") {
          param.cancelAndHoldAtTime(now);
        } else {
          param.cancelScheduledValues(now);
          param.setValueAtTime(param.value, now);
        }
        param.linearRampToValueAtTime(target, now + CROSSFADE_SECONDS);
      } else {
        param.cancelScheduledValues(now);
        param.setValueAtTime(target, now);
      }
    };

    ramp(this.origGain.gain, gOrig);
    ramp(this.procGain.gain, gProc);
    ramp(this.resGain.gain, gRes);
    ramp(this.masterGain.gain, master);
  }

  async play(): Promise<void> {
    if (!this.originalBuffer || !this.processedBuffer || !this.residualBuffer) {
      return;
    }
    const ctx = this.ensureContext();
    if (ctx.state === "suspended") {
      await ctx.resume();
    }

    if (this.offsetSec >= this.durationSec - 0.01) {
      this.offsetSec = 0;
    }

    this.stopSources();

    const origSrc = ctx.createBufferSource();
    const procSrc = ctx.createBufferSource();
    const resSrc = ctx.createBufferSource();

    origSrc.buffer = this.originalBuffer;
    procSrc.buffer = this.processedBuffer;
    resSrc.buffer = this.residualBuffer;

    origSrc.connect(this.origGain!);
    procSrc.connect(this.procGain!);
    resSrc.connect(this.resGain!);

    const startAt = ctx.currentTime + 0.01;
    const offset = Math.min(this.durationSec, Math.max(0, this.offsetSec));

    // Trigger all three streams at the exact same audio clock instant
    origSrc.start(startAt, offset);
    procSrc.start(startAt, offset);
    resSrc.start(startAt, offset);

    this.origSource = origSrc;
    this.procSource = procSrc;
    this.resSource = resSrc;
    this.startCtxTime = startAt;
    this.playing = true;
    this.applyGains(false);

    procSrc.onended = () => {
      if (this.playing && this.getCurrentTime() >= this.durationSec - 0.03) {
        this.playing = false;
        this.offsetSec = 0;
        this.stopSources();
        this.emit({ playing: false, currentTime: 0 });
      }
    };

    const tick = () => {
      if (!this.playing || this.disposed) return;
      this.emit({ playing: true, currentTime: this.getCurrentTime() });
      this.rafId = requestAnimationFrame(tick);
    };
    this.rafId = requestAnimationFrame(tick);
    this.emit({ playing: true });
  }

  pause(): void {
    if (!this.playing) return;
    this.offsetSec = this.getCurrentTime();
    this.playing = false;
    this.stopSources();
    this.emit({ playing: false, currentTime: this.offsetSec });
  }

  stop(): void {
    this.playing = false;
    this.offsetSec = 0;
    this.stopSources();
    this.emit({ playing: false, currentTime: 0 });
  }

  seek(timeSec: number): void {
    const clamped = Math.min(this.durationSec, Math.max(0, timeSec));
    this.offsetSec = clamped;
    if (this.playing) {
      void this.play();
    } else {
      this.emit({ currentTime: clamped });
    }
  }

  setMode(mode: CompareListenMode): void {
    this.mode = mode;
    this.applyGains(true);
  }

  setWetMix(mix: number): void {
    this.wetMix = Math.min(1, Math.max(0, mix));
    if (this.mode === "mix") {
      this.applyGains(true);
    }
  }

  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    this.applyGains(true);
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.applyGains(true);
  }

  dispose(): void {
    this.disposed = true;
    this.loadToken++;
    this.stopSources();
    if (this.ctx) {
      void this.ctx.close();
      this.ctx = null;
    }
  }
}
