import { useCallback, useEffect, useRef, useState } from "react";
import type { CallDetail } from "../api";
import { secs } from "../format";

const PEAKS_PER_SECOND = 50;  // core/config.peaks_per_second

function decodePeaks(b64: string): Int16Array {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
  return new Int16Array(buf);
}

type Mode = "both" | "caller" | "agent";

/** Web Audio channel player: one stereo source, split into caller/agent gains so you can solo
 *  either side or hear the whole call. Shared playhead drives every waveform. Falls back to a
 *  plain <audio> if decode/CORS fails. */
function useChannelPlayer(url: string | null, channelMap: Record<string, string>) {
  const ctx = useRef<AudioContext | null>(null);
  const buffer = useRef<AudioBuffer | null>(null);
  const source = useRef<AudioBufferSourceNode | null>(null);
  const gains = useRef<GainNode[]>([]);
  const startedAt = useRef(0);   // ctx.currentTime when the current source started
  const offset = useRef(0);      // seconds into the buffer where it started
  const raf = useRef(0);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const [mode, setModeState] = useState<Mode>("both");
  const dur = buffer.current?.duration ?? 0;

  const applyMode = useCallback((m: Mode) => {
    gains.current.forEach((g, i) => {
      const name = channelMap[String(i)] ?? (i === 0 ? "caller" : "agent");
      g.gain.value = m === "both" || m === name ? 1 : 0;
    });
  }, [channelMap]);

  const load = useCallback(async () => {
    if (ctx.current || !url) return;
    try {
      ctx.current = new AudioContext();
      const bytes = await (await fetch(url)).arrayBuffer();
      buffer.current = await ctx.current.decodeAudioData(bytes);
      setReady(true);
    } catch { setFailed(true); }
  }, [url]);

  const stopSource = useCallback(() => {
    cancelAnimationFrame(raf.current);
    if (source.current) { try { source.current.onended = null; source.current.stop(); } catch { /* already stopped */ } source.current = null; }
  }, []);

  const tick = useCallback(() => {
    if (!ctx.current) return;
    const p = offset.current + (ctx.current.currentTime - startedAt.current);
    if (p >= dur) { stopSource(); setPlaying(false); setPos(dur); offset.current = 0; return; }
    setPos(p);
    raf.current = requestAnimationFrame(tick);
  }, [dur, stopSource]);

  const play = useCallback(async (from?: number) => {
    await load();
    if (!ctx.current || !buffer.current) return;
    await ctx.current.resume();
    stopSource();
    const src = ctx.current.createBufferSource();
    src.buffer = buffer.current;
    const splitter = ctx.current.createChannelSplitter(buffer.current.numberOfChannels);
    src.connect(splitter);
    gains.current = [];
    for (let i = 0; i < buffer.current.numberOfChannels; i++) {
      const g = ctx.current.createGain();
      splitter.connect(g, i);
      g.connect(ctx.current.destination);
      gains.current.push(g);
    }
    applyMode(mode);
    offset.current = from ?? pos;
    if (offset.current >= dur) offset.current = 0;
    startedAt.current = ctx.current.currentTime;
    src.onended = () => { if (source.current === src) { setPlaying(false); } };
    src.start(0, offset.current);
    source.current = src;
    setPlaying(true);
    raf.current = requestAnimationFrame(tick);
  }, [load, stopSource, applyMode, mode, pos, dur, tick]);

  const pause = useCallback(() => {
    if (!ctx.current) return;
    offset.current += ctx.current.currentTime - startedAt.current;
    stopSource();
    setPos(offset.current);
    setPlaying(false);
  }, [stopSource]);

  const setMode = useCallback((m: Mode) => { setModeState(m); if (playing) applyMode(m); }, [playing, applyMode]);
  const seek = useCallback((t: number) => { if (playing) play(t); else { offset.current = t; setPos(t); } }, [playing, play]);

  useEffect(() => () => { stopSource(); ctx.current?.close(); }, [stopSource]);

  return { ready, failed, playing, pos, dur, mode, play, pause, setMode, seek,
           channels: buffer.current?.numberOfChannels ?? 0 };
}

export default function Recording({ data }: { data: CallDetail }) {
  const channels = Object.keys(data.peaks);
  const audio = data.audio;
  const map = (data.call.channel_map as Record<string, string>) ?? { "0": "caller", "1": "agent" };
  const p = useChannelPlayer(audio?.url ?? null, map);
  const dur = p.dur || audio?.duration_s || data.call.duration_s || 0;
  const stereo = p.channels > 1 || channels.length > 1;

  const MODES: [Mode, string][] = [["both", "▶ Both"], ["caller", "▶ Caller"], ["agent", "▶ Agent"]];

  return (
    <section className="sec">
      <h3>
        Recording
        <span className="right">
          {audio?.url
            ? `${secs(dur)} · ${audio.sample_rate ?? "?"} Hz · ${audio.channels ?? channels.length} ch`
            : data.trust.media_ready ? "audio not presigned" : "audio not fetched yet"}
        </span>
      </h3>

      {channels.length ? channels.map((ch) => (
        <div key={ch}>
          <div className="wave-lbl"><span>{ch}</span><span className="dimtxt">channel</span></div>
          <Wave peaks={data.peaks[ch]} playhead={p.pos}
            onSeek={(frac) => p.seek(frac * dur)} />
        </div>
      )) : <p className="dimtxt">No waveform yet. Peaks appear once the worker has analysed the audio.</p>}

      {audio?.url && !p.failed && (
        <div className="rec-controls">
          {MODES.map(([m, label]) => {
            const disabled = m !== "both" && !stereo;
            const activePlaying = p.playing && p.mode === m;
            return (
              <button key={m} className={`rec-btn ${p.mode === m ? "on" : ""}`} disabled={disabled}
                onClick={() => {
                  if (activePlaying) { p.pause(); return; }
                  p.setMode(m);
                  if (!p.playing) p.play();
                }}>
                {activePlaying ? "⏸ " + label.slice(2) : label}
              </button>
            );
          })}
          <span className="rec-time">{fmtTime(p.pos)} / {fmtTime(dur)}</span>
        </div>
      )}
      {audio?.url && p.failed && (
        <audio controls preload="none" src={audio.url} className="player" />
      )}
    </section>
  );
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function Wave(
  { peaks, playhead, onSeek }: { peaks: string; playhead: number; onSeek: (frac: number) => void },
) {
  const cv = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const W = c.clientWidth * dpr, H = 56 * dpr;
    c.width = W; c.height = H;
    const g = c.getContext("2d")!;
    const pk = decodePeaks(peaks);
    const n = pk.length / 2;
    const style = getComputedStyle(c);
    g.fillStyle = style.getPropertyValue("--wave").trim() || "#6d6862";
    const cols = Math.max(1, Math.floor(W / (2 * dpr)));
    const per = n / cols;
    for (let x = 0; x < cols; x++) {
      const i0 = Math.floor(x * per), i1 = Math.max(i0 + 1, Math.floor((x + 1) * per));
      let lo = 0, hi = 0;
      for (let i = i0; i < i1 && i < n; i++) { lo = Math.min(lo, pk[2 * i]); hi = Math.max(hi, pk[2 * i + 1]); }
      const y0 = H / 2 - (hi / 32768) * (H / 2), y1 = H / 2 - (lo / 32768) * (H / 2);
      g.fillRect(x * 2 * dpr, y0, 1.4 * dpr, Math.max(1, y1 - y0));
    }
    const total = n / PEAKS_PER_SECOND;
    if (playhead > 0 && total > 0) {
      g.fillStyle = style.getPropertyValue("--ink").trim() || "#000";
      g.fillRect((Math.min(playhead, total) / total) * W, 0, 1.5 * dpr, H);
    }
  }, [peaks, playhead]);
  return <canvas ref={cv} className="wave"
    onClick={(e) => {
      const r = e.currentTarget.getBoundingClientRect();
      onSeek(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)));
    }} />;
}
