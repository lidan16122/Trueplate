import { useCallback, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { ApiError, api } from "@/lib/api";
import { today } from "@/lib/format";
import type { FoodDetectionResponse } from "@/types/api";

type Mode = "idle" | "text";

export function AddFood() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const date = params.get("date") ?? today();

  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  const goToConfirm = useCallback(
    (proposal: FoodDetectionResponse) => {
      navigate("/add/confirm", { state: { proposal, date } });
    },
    [navigate, date],
  );

  const describeFailure = (err: unknown): string => {
    if (err instanceof ApiError) {
      if (err.status === 501) {
        return "Food detection isn't wired up yet — the camera and confirm screens are ready and waiting for it.";
      }
      if (err.status === 429) return err.message;
      return err.message;
    }
    return "Something went wrong";
  };

  const handlePhoto = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      setPreview(URL.createObjectURL(file));
      try {
        goToConfirm(await api.ai.detectPhoto(file));
      } catch (err) {
        setError(describeFailure(err));
      } finally {
        setBusy(false);
      }
    },
    [goToConfirm],
  );

  const handleText = useCallback(async () => {
    if (description.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      goToConfirm(await api.ai.detectText(description));
    } catch (err) {
      setError(describeFailure(err));
    } finally {
      setBusy(false);
    }
  }, [description, goToConfirm]);

  return (
    <div className="flex min-h-dvh flex-col bg-ink">
      {/* Viewfinder */}
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="flex h-full w-full max-w-[720px] flex-col items-center justify-center gap-2.5 overflow-hidden rounded-2xl border border-dashed border-line-dark">
          {preview ? (
            <img src={preview} alt="" className="h-full w-full object-cover" />
          ) : mode === "text" ? (
            <div className="flex w-full max-w-[440px] flex-col gap-4 p-6">
              <label
                htmlFor="meal-description"
                className="font-mono text-label tracking-[0.08em] text-on-dark-dim"
              >
                DESCRIBE THE MEAL
              </label>
              <textarea
                id="meal-description"
                autoFocus
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="chicken, rice and broccoli"
                className="resize-none rounded-card border border-line-dark bg-ink-2 px-4 py-3 text-lead text-white outline-none placeholder:text-on-dark-faint focus:border-accent"
              />
              <button
                onClick={handleText}
                disabled={busy || description.trim().length < 2}
                className="h-12 rounded-card bg-white text-caption font-semibold text-ink transition-opacity disabled:opacity-40"
              >
                {busy ? "Reading…" : "Find these foods"}
              </button>
            </div>
          ) : (
            <>
              <div className="font-mono text-label tracking-[0.08em] text-on-dark-dim">
                CAMERA VIEWFINDER
              </div>
              <div className="text-caption text-on-dark-faint">Point at the plate</div>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="mx-6 mb-4 rounded-card border border-line-dark bg-ink-2 px-4 py-3 text-caption leading-relaxed text-on-dark">
          {error}
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-none flex-col gap-4.5 px-6 pb-10">
        <div className="flex items-center justify-center gap-9">
          <button
            onClick={() => setMode(mode === "text" ? "idle" : "text")}
            className="flex w-[76px] flex-col items-center gap-[7px]"
          >
            <span
              className={`flex h-12 w-12 items-center justify-center rounded-full border text-[17px] text-white transition-colors ${
                mode === "text" ? "border-accent bg-accent" : "border-line-dark hover:bg-ink-2"
              }`}
            >
              Aa
            </span>
            <span className="text-label text-on-dark">Describe</span>
          </button>

          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="flex flex-col items-center gap-[7px]"
            aria-label="Take a photo"
          >
            <span className="h-[76px] w-[76px] rounded-full border-[5px] border-line-dark bg-white transition-colors hover:border-accent" />
            <span className="text-label text-on-dark">{busy ? "Reading…" : "Photo"}</span>
          </button>

          <button
            onClick={() => setError("Barcode scanning isn't built yet.")}
            className="flex w-[76px] flex-col items-center gap-[7px]"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-full border border-line-dark text-caption tracking-[0.12em] text-white transition-colors hover:bg-ink-2">
              |||
            </span>
            <span className="text-label text-on-dark">Barcode</span>
          </button>
        </div>

        <button
          onClick={() => navigate(-1)}
          className="h-12 w-full rounded-lg text-caption text-on-dark transition-colors hover:text-white"
        >
          Cancel
        </button>
      </div>

      {/*
        `capture="environment"` opens the rear camera directly on a phone and
        falls back to a normal file picker on desktop. A plain file input rather
        than getUserMedia: no permission prompt to manage, no video element to
        keep alive, and the OS camera UI is better than anything reimplemented.
      */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handlePhoto(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
