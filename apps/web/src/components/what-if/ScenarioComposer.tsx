import { useRef, useState } from "react";
import { ArrowUp, Mic, Paperclip, Square } from "lucide-react";

type SpeechResult = { results: ArrayLike<ArrayLike<{ transcript: string }>> };

type SpeechSession = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechResult) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};

function speechCtor(): (new () => SpeechSession) | null {
  if (typeof window === "undefined") return null;
  const host = window as Window & {
    SpeechRecognition?: new () => SpeechSession;
    webkitSpeechRecognition?: new () => SpeechSession;
  };
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null;
}

function speechSession(): SpeechSession | null {
  const Ctor = speechCtor();
  return Ctor ? new Ctor() : null;
}

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  busy?: boolean;
  submitLabel: string;
};

export function ScenarioComposer({
  id,
  label,
  value,
  onChange,
  onSubmit,
  placeholder = "Ask a what-if",
  busy = false,
  submitLabel,
}: Props) {
  const [recording, setRecording] = useState(false);
  const [speechError, setSpeechError] = useState<string | null>(null);
  const session = useRef<SpeechSession | null>(null);
  const supported = speechCtor() !== null;

  function toggleSpeech() {
    if (recording) {
      session.current?.stop();
      setRecording(false);
      return;
    }
    const next = speechSession();
    if (!next) {
      setSpeechError("Speech input isn’t available in this browser.");
      return;
    }
    setSpeechError(null);
    next.lang = "en-US";
    next.interimResults = false;
    next.continuous = false;
    next.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((row) => row[0]?.transcript ?? "")
        .join(" ")
        .trim();
      if (transcript) onChange(value ? `${value.trim()} ${transcript}` : transcript);
    };
    next.onerror = () => {
      setSpeechError("Couldn’t hear that. Try again.");
      setRecording(false);
    };
    next.onend = () => setRecording(false);
    session.current = next;
    try {
      next.start();
      setRecording(true);
    } catch {
      setSpeechError("Microphone permission is needed for speech input.");
      setRecording(false);
    }
  }

  return (
    <section className="composer scenario-composer">
      <label className="visually-hidden" htmlFor={id}>{label}</label>
      <div className="scenario-composer-surface">
        <textarea
          id={id}
          name={id}
          rows={1}
          value={value}
          autoComplete="off"
          placeholder={placeholder}
          disabled={busy}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (!busy && value.trim()) onSubmit();
            }
          }}
        />
        <div className="scenario-composer-actions">
          <button
            type="button"
            className="composer-icon"
            aria-label="Attach a file"
            disabled
            title="File attachments are not ingested as evidence yet, so this control stays unavailable."
          >
            <Paperclip size={16} />
          </button>
          <button
            type="button"
            className={recording ? "composer-icon recording" : "composer-icon"}
            aria-pressed={recording}
            aria-label={recording ? "Stop recording" : "Dictate"}
            disabled={!supported || busy}
            title={supported ? "Dictate" : "Speech input isn’t available in this browser."}
            onClick={toggleSpeech}
          >
            {recording ? <Square size={16} /> : <Mic size={18} />}
          </button>
          <button
            type="button"
            className="composer-submit"
            aria-label={submitLabel}
            disabled={busy || !value.trim()}
            onClick={onSubmit}
          >
            <ArrowUp size={18} />
          </button>
        </div>
      </div>
      {speechError ? <p role="alert" className="composer-speech-error">{speechError}</p> : null}
      {recording ? <p role="status" className="composer-speech-error">Listening…</p> : null}
    </section>
  );
}
