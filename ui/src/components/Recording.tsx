import { useEffect, useRef, useState } from "react";
import type { CallDetail } from "../api";
import { secs } from "../format";

// Worker emits LE int16 (min,max) pairs, 50 buckets/sec (core/config.peaks_per_second).
const PEAKS_PER_SECOND = 50;

function decodePeaks(b64: string): Int16Array {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
  return new Int16Array(buf);
}

/** Recording — per-channel waveform drawn from the stored peaks, and the audio
 *  itself streamed straight from the presigned URL when the worker has it. */
export default function Recording({ data }: { data: CallDetail }) {
  const channels = Object.keys(data.peaks);
  const audio = data.audio;
  const [t, setT] = useState(0);
  const ref = useRef<HTMLAudioElement>(null);
  const dur = audio?.duration_s ?? data.call.duration_s ?? 0;

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
      {channels.length ? (
        channels.map((ch) => (
          <div key={ch}>
            <div className="wave-lbl"><span>{ch}</span><span className="dimtxt">from channel_map</span></div>
            <Wave peaks={data.peaks[ch]} duration={dur} playhead={t} />
          </div>
        ))
      ) : (
        <p className="dimtxt">No waveform yet. Peaks appear once the worker has analysed the audio.</p>
      )}
      {audio?.url && (
        <audio
          ref={ref}
          controls
          preload="none"
          src={audio.url}
          onTimeUpdate={() => setT(ref.current?.currentTime ?? 0)}
          className="player"
        />
      )}
    </section>
  );
}

function Wave({ peaks, duration, playhead }: { peaks: string; duration: number; playhead: number }) {
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
    // One bucket per column; buckets beyond the duration are padding.
    const cols = Math.max(1, Math.floor(W / (2 * dpr)));
    const per = n / cols;
    for (let x = 0; x < cols; x++) {
      const i0 = Math.floor(x * per), i1 = Math.max(i0 + 1, Math.floor((x + 1) * per));
      let lo = 0, hi = 0;
      for (let i = i0; i < i1 && i < n; i++) {
        lo = Math.min(lo, pk[2 * i]);
        hi = Math.max(hi, pk[2 * i + 1]);
      }
      const y0 = H / 2 - (hi / 32768) * (H / 2), y1 = H / 2 - (lo / 32768) * (H / 2);
      g.fillRect(x * 2 * dpr, y0, 1.4 * dpr, Math.max(1, y1 - y0));
    }
    if (playhead > 0 && duration > 0) {
      g.fillStyle = style.getPropertyValue("--ink").trim() || "#000";
      const px = (Math.min(playhead, n / PEAKS_PER_SECOND) / (n / PEAKS_PER_SECOND)) * W;
      g.fillRect(px, 0, 1.5 * dpr, H);
    }
  }, [peaks, duration, playhead]);
  return <canvas ref={cv} className="wave" />;
}
