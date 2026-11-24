import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AbAudioEngine } from "../audio/abAudioEngine";

interface MockGain {
  gain: {
    value: number;
    setValueAtTime: ReturnType<typeof vi.fn>;
    linearRampToValueAtTime: ReturnType<typeof vi.fn>;
    cancelScheduledValues: ReturnType<typeof vi.fn>;
    cancelAndHoldAtTime: ReturnType<typeof vi.fn>;
  };
  connect: ReturnType<typeof vi.fn>;
}

interface MockSource {
  buffer: unknown;
  onended: (() => void) | null;
  connect: ReturnType<typeof vi.fn>;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
}

describe("AbAudioEngine synchronization, click-free A/B, dry/wet blend, and residual routing", () => {
  let createdGains: MockGain[];
  let createdSources: MockSource[];
  const originalAudioContext = window.AudioContext;

  beforeEach(() => {
    createdGains = [];
    createdSources = [];

    const makeGain = (): MockGain => {
      const g: MockGain = {
        gain: {
          value: 1,
          setValueAtTime: vi.fn((v: number) => {
            g.gain.value = v;
          }),
          linearRampToValueAtTime: vi.fn((v: number) => {
            g.gain.value = v;
          }),
          cancelScheduledValues: vi.fn(),
          cancelAndHoldAtTime: vi.fn(),
        },
        connect: vi.fn(),
      };
      createdGains.push(g);
      return g;
    };

    const makeSource = (): MockSource => {
      const s: MockSource = {
        buffer: null,
        onended: null,
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        disconnect: vi.fn(),
      };
      createdSources.push(s);
      return s;
    };

    class MockAudioContext {
      currentTime = 1.0;
      state = "running";
      destination = {};
      createGain = vi.fn(() => makeGain());
      createBufferSource = vi.fn(() => makeSource());
      decodeAudioData = vi.fn(async () => ({
        duration: 2.0,
        length: 96000,
        sampleRate: 48000,
        numberOfChannels: 2,
      }));
      resume = vi.fn(async () => undefined);
      close = vi.fn(async () => undefined);
    }

    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      writable: true,
      value: MockAudioContext,
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        arrayBuffer: async () => new ArrayBuffer(64),
      })),
    );
  });

  afterEach(() => {
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      writable: true,
      value: originalAudioContext,
    });
    vi.restoreAllMocks();
  });

  it("starts original, processed, and residual at identical clock instant and blends dry/wet linearly without restarting sources", async () => {
    const states: unknown[] = [];
    const engine = new AbAudioEngine((s) => states.push(s));

    await engine.load("/orig-aligned.wav", "/processed.wav", "/residual.wav", 2.0);
    await engine.play();

    // Exact simultaneous start across all 3 buffers (zero clock drift)
    expect(createdSources).toHaveLength(3);
    const [origSrc, procSrc, resSrc] = createdSources;
    const startArgs = origSrc.start.mock.calls[0];
    expect(procSrc.start.mock.calls[0]).toEqual(startArgs);
    expect(resSrc.start.mock.calls[0]).toEqual(startArgs);

    const [origGain, procGain, resGain, masterGain] = createdGains;

    // Default mode is processed (B)
    expect(origGain.gain.value).toBe(0);
    expect(procGain.gain.value).toBe(1);
    expect(resGain.gain.value).toBe(0);
    expect(masterGain.gain.value).toBe(1);

    // Switch to Original (A): smooth ramp, zero source restarts (no gaps/drift)
    engine.setMode("original");
    expect(createdSources).toHaveLength(3);
    expect(origGain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(1, expect.any(Number));
    expect(procGain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, expect.any(Number));
    expect(resGain.gain.linearRampToValueAtTime).toHaveBeenCalledWith(0, expect.any(Number));

    // Switch to Dry/Wet Mix at 35% wet -> true complementary linear blend (0.65 dry + 0.35 wet), master untouched
    engine.setMode("mix");
    engine.setWetMix(0.35);
    expect(origGain.gain.value).toBeCloseTo(0.65, 5);
    expect(procGain.gain.value).toBeCloseTo(0.35, 5);
    expect(resGain.gain.value).toBe(0);
    expect(masterGain.gain.value).toBe(1);

    // Switch to Residual -> routes backend residual stream exclusively
    engine.setMode("residual");
    expect(origGain.gain.value).toBe(0);
    expect(procGain.gain.value).toBe(0);
    expect(resGain.gain.value).toBe(1);

    engine.dispose();
  });
});
