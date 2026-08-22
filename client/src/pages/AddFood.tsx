import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { ErrorNote } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDayLabel, today } from "@/lib/format";
import type { FoodDetectionResponse } from "@/types/api";

type Mode = "idle" | "text" | "barcode";

/**
 * Two genuinely different screens, not one screen that reflows.
 *
 * On a phone the camera *is* the feature, so the whole viewport is a dark
 * viewfinder with a shutter button. On a desktop there is no camera worth
 * using, so the same three inputs are presented as a drop zone, a text box and
 * a barcode field. Sharing markup between those would mean a compromise that
 * suits neither; sharing the handlers below costs nothing.
 */
export function AddFood() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const date = params.get("date") ?? today();

  const fileRef = useRef<HTMLInputElement>(null);
  const barcodeFileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [description, setDescription] = useState("");
  const [upc, setUpc] = useState("");
  const [busy, setBusy] = useState<null | "photo" | "text" | "barcode">(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  // Held, not sent. Choosing a photo used to fire the detection from the file
  // input's own onChange, which made "a photo *and* a note" impossible to
  // express — by the time there was anywhere to type, the request was gone.
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);

  // The preview URL is handed to the confirm screen, which takes over revoking
  // it. Anything still held here when this screen goes away was never handed
  // over — a failed detection — so it is ours to release.
  const handedOff = useRef(false);
  useEffect(
    () => () => {
      if (preview && !handedOff.current) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  const goToConfirm = useCallback(
    (proposal: FoodDetectionResponse, photo: string | null) => {
      handedOff.current = true;
      navigate("/add/confirm", { state: { proposal, date, photo } });
    },
    [navigate, date],
  );

  const describeFailure = (err: unknown): string => {
    if (err instanceof ApiError) {
      // 422 is an answer, not a fault: the server looked and this is not food
      // it can log. 503 means detection is unconfigured or down.
      if (err.status === 503) {
        return "Food detection isn't available right now. The server may be missing its API key.";
      }
      return err.message;
    }
    return "Something went wrong";
  };

  /** Show the photo and wait. No network call until the user asks for one. */
  const stagePhoto = useCallback((file: File) => {
    setError(null);
    setPhotoFile(file);
    // Replacing an earlier pick needs nothing extra: the effect above releases
    // the previous object URL when this value changes.
    setPreview(URL.createObjectURL(file));
  }, []);

  const clearPhoto = useCallback(() => {
    setPhotoFile(null);
    setPreview(null);
  }, []);

  const submitPhoto = useCallback(async () => {
    if (!photoFile || !preview) return;
    setBusy("photo");
    setError(null);
    try {
      // The typed description rides along when there is one: a stated
      // quantity beats any visual estimate.
      goToConfirm(await api.ai.detectPhoto(photoFile, description), preview);
    } catch (err) {
      // The photo stays staged deliberately. A failure is usually worth one
      // retry, and re-choosing the file to get it would be a punishment.
      setError(describeFailure(err));
    } finally {
      setBusy(null);
    }
  }, [photoFile, preview, description, goToConfirm]);

  const handleText = useCallback(async () => {
    if (description.trim().length < 2) return;
    setBusy("text");
    setError(null);
    try {
      goToConfirm(await api.ai.detectText(description), null);
    } catch (err) {
      setError(describeFailure(err));
    } finally {
      setBusy(null);
    }
  }, [description, goToConfirm]);

  const handleBarcode = useCallback(
    async (input: { image?: File; upc?: string }) => {
      setBusy("barcode");
      setError(null);
      try {
        goToConfirm(await api.ai.detectBarcode(input), null);
      } catch (err) {
        setError(describeFailure(err));
      } finally {
        setBusy(null);
      }
    },
    [goToConfirm],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file?.type.startsWith("image/")) stagePhoto(file);
    },
    [stagePhoto],
  );

  return (
    <>
      {/* ============================ MOBILE ============================ */}
      <div className="flex min-h-dvh flex-col bg-ink md:hidden">
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="flex h-full w-full max-w-[720px] flex-col items-center justify-center gap-2.5 overflow-hidden rounded-2xl border border-dashed border-line-dark">
            {/*
              `mode === "text"` is tested before `preview`, and that order is
              the whole feature. The other way round, a staged photo hid the
              textarea, so a note and a picture could never be given together —
              which is exactly when a note is most useful ("half of this went
              back in the pan").
            */}
            {mode === "text" ? (
              <div className="flex w-full max-w-[440px] flex-col gap-4 p-6">
                {preview && (
                  <div className="flex items-center gap-2.5">
                    <img
                      src={preview}
                      alt=""
                      className="h-10 w-10 flex-none rounded-chip object-cover"
                    />
                    <span className="min-w-0 flex-1 text-label text-on-dark-dim">
                      Photo attached — your note refines it
                    </span>
                    <button
                      onClick={clearPhoto}
                      className="flex-none text-label text-on-dark underline-offset-2 transition-colors hover:text-white hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                )}
                <label
                  htmlFor="meal-description"
                  className="font-mono text-label tracking-[0.08em] text-on-dark-dim"
                >
                  {preview ? "ADD A NOTE" : "DESCRIBE THE MEAL"}
                </label>
                <textarea
                  id="meal-description"
                  autoFocus
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={preview ? "no oil, half a portion" : "chicken, rice and broccoli"}
                  className="resize-none rounded-card border border-line-dark bg-ink-2 px-4 py-3 text-lead text-white outline-none placeholder:text-on-dark-faint focus:border-accent"
                />
                <button
                  onClick={photoFile ? submitPhoto : handleText}
                  // With a photo staged the note is optional, so the two-character
                  // floor applies only when the text *is* the whole input.
                  disabled={busy !== null || (!photoFile && description.trim().length < 2)}
                  className="h-12 rounded-card bg-white text-caption font-semibold text-ink transition-opacity disabled:opacity-40"
                >
                  {busy !== null
                    ? "Reading…"
                    : photoFile
                      ? "Analyse photo and note"
                      : "Find these foods"}
                </button>
              </div>
            ) : mode === "barcode" ? (
              <div className="flex w-full max-w-[440px] flex-col gap-4 p-6">
                <label
                  htmlFor="upc-mobile"
                  className="font-mono text-label tracking-[0.08em] text-on-dark-dim"
                >
                  BARCODE
                </label>
                <input
                  id="upc-mobile"
                  autoFocus
                  inputMode="numeric"
                  value={upc}
                  onChange={(e) => setUpc(e.target.value)}
                  placeholder="5000112637939"
                  className="tabular h-12 rounded-card border border-line-dark bg-ink-2 px-4 font-mono text-lead text-white outline-none placeholder:text-on-dark-faint focus:border-accent"
                />
                <button
                  onClick={() => barcodeFileRef.current?.click()}
                  disabled={busy !== null}
                  className="h-12 rounded-card border border-line-dark text-caption font-medium text-on-dark transition-colors hover:text-white disabled:opacity-40"
                >
                  Or photograph the barcode
                </button>
                <button
                  onClick={() => void handleBarcode({ upc })}
                  disabled={busy !== null || upc.trim().length < 8}
                  className="h-12 rounded-card bg-white text-caption font-semibold text-ink transition-opacity disabled:opacity-40"
                >
                  {busy === "barcode" ? "Looking up…" : "Find this product"}
                </button>
              </div>
            ) : preview ? (
              <img src={preview} alt="" className="h-full w-full object-cover" />
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

        <div className="flex flex-none flex-col gap-4.5 px-6 pb-10">
          <div className="flex items-center justify-center gap-9">
            <button
              onClick={() => setMode(mode === "text" ? "idle" : "text")}
              className="flex w-[76px] flex-col items-center gap-[7px]"
            >
              <span
                className={`flex h-12 w-12 items-center justify-center rounded-full border text-entry text-white transition-colors ${
                  mode === "text" ? "border-accent bg-accent" : "border-line-dark hover:bg-ink-2"
                }`}
              >
                Aa
              </span>
              <span className="text-label text-on-dark">Describe</span>
            </button>

            {/*
              One button, two jobs: it takes the photo, then it sends it. A
              separate submit control would sit dead and greyed for the whole
              time the screen is a viewfinder, which is most of the time.
            */}
            <button
              onClick={() => (photoFile ? void submitPhoto() : fileRef.current?.click())}
              disabled={busy !== null}
              className="flex flex-col items-center gap-[7px]"
              aria-label={photoFile ? "Analyse this photo" : "Take a photo"}
            >
              <span
                className={`h-[76px] w-[76px] rounded-full border-[5px] transition-colors ${
                  photoFile
                    ? "border-accent bg-accent"
                    : "border-line-dark bg-white hover:border-accent"
                }`}
              />
              <span className="text-label text-on-dark">
                {busy === "photo" ? "Reading…" : photoFile ? "Analyse" : "Photo"}
              </span>
            </button>

            <button
              onClick={() => setMode(mode === "barcode" ? "idle" : "barcode")}
              className="flex w-[76px] flex-col items-center gap-[7px]"
            >
              <span
                className={`flex h-12 w-12 items-center justify-center rounded-full border text-caption tracking-[0.12em] text-white transition-colors ${
                  mode === "barcode" ? "border-accent bg-accent" : "border-line-dark hover:bg-ink-2"
                }`}
              >
                |||
              </span>
              <span className="text-label text-on-dark">Barcode</span>
            </button>
          </div>

          {photoFile && (
            <button
              onClick={() => fileRef.current?.click()}
              disabled={busy !== null}
              className="h-9 w-full text-label text-on-dark-dim transition-colors hover:text-white disabled:opacity-40"
            >
              Retake
            </button>
          )}

          <button
            onClick={() => navigate(-1)}
            className="h-12 w-full rounded-lg text-caption text-on-dark transition-colors hover:text-white"
          >
            Cancel
          </button>
        </div>
      </div>

      {/* =========================== DESKTOP ============================ */}
      <div className="hidden min-h-dvh flex-col bg-surface md:flex">
        <header className="flex h-16 flex-none items-center justify-between border-b border-line-2 px-8">
          <h1 className="text-lead font-semibold text-ink">Add food · {formatDayLabel(date)}</h1>
          <button
            onClick={() => navigate(-1)}
            className="text-body text-muted transition-colors hover:text-ink"
          >
            Cancel
          </button>
        </header>

        <div className="flex min-h-0 flex-1 gap-6 p-8">
          {/*
            Wrapped so "Remove photo" can sit outside the drop zone: the zone is
            itself a <button>, and a button inside a button is invalid markup
            that browsers resolve by dropping one of them.
          */}
          <div className="flex min-h-0 flex-[1.4] flex-col gap-3">
            <button
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              disabled={busy !== null}
              className={`flex min-h-0 flex-1 flex-col items-center justify-center gap-3.5 rounded-2xl border border-dashed p-8 transition-colors ${
                dragging
                  ? "border-accent bg-accent-wash"
                  : "border-hairline-strong bg-panel hover:border-accent hover:bg-accent-wash"
              }`}
            >
              {preview ? (
                <img
                  src={preview}
                  alt=""
                  className="max-h-full max-w-full rounded-lg object-contain"
                />
              ) : (
                <>
                  <span className="flex h-13 w-13 items-center justify-center rounded-lg border-[1.5px] border-icon-faint">
                    <span className="h-4 w-4 rounded-full border-[1.5px] border-icon-faint" />
                  </span>
                  <span className="text-title font-semibold text-ink">Drop a photo here</span>
                  <span className="max-w-[280px] text-center text-body leading-relaxed text-subtle">
                    Or click to browse. Add a note on the right if you want to — they are sent
                    together.
                  </span>
                </>
              )}
            </button>

            {photoFile && (
              <button
                onClick={clearPhoto}
                disabled={busy !== null}
                className="h-9 flex-none text-caption text-subtle transition-colors hover:text-ink disabled:opacity-40"
              >
                Remove photo
              </button>
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-4">
            <div className="flex flex-1 flex-col gap-3.5 rounded-2xl border border-line p-5.5">
              <label htmlFor="meal-description-desktop" className="text-lead font-semibold text-ink">
                {photoFile ? "Add a note" : "Describe the meal"}
              </label>
              <textarea
                id="meal-description-desktop"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={
                  photoFile
                    ? "no oil, half a portion — anything the photo cannot show"
                    : "chicken breast, a cup of rice, roasted broccoli"
                }
                className="flex-1 resize-none rounded-card border border-line-card px-4 py-3.5 text-item leading-relaxed text-ink outline-none placeholder:text-faint focus:border-accent"
              />
              <button
                onClick={photoFile ? submitPhoto : handleText}
                // With a photo staged the note is optional, so the two-character
                // floor applies only when the text *is* the whole input.
                disabled={busy !== null || (!photoFile && description.trim().length < 2)}
                className="h-11.5 rounded-md bg-ink text-item font-semibold text-white transition-colors hover:bg-accent disabled:opacity-40"
              >
                {busy === "photo"
                  ? "Reading the plate…"
                  : busy === "text"
                    ? "Reading…"
                    : photoFile
                      ? "Estimate portions from photo"
                      : "Estimate portions"}
              </button>
            </div>

            <div className="flex flex-none flex-col gap-3 rounded-2xl border border-line px-5.5 py-4.5">
              <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <label htmlFor="upc-desktop" className="text-item font-semibold text-ink">
                    Enter a barcode
                  </label>
                  <span className="text-caption text-subtle">
                    Scanning works on your phone. Here, type the number.
                  </span>
                </div>
                <span className="text-item tracking-[0.12em] text-icon-faint">|||</span>
              </div>
              <div className="flex gap-2">
                <input
                  id="upc-desktop"
                  inputMode="numeric"
                  value={upc}
                  onChange={(e) => setUpc(e.target.value)}
                  placeholder="5000112637939"
                  className="tabular h-11 min-w-0 flex-1 rounded-md border border-line-control px-3.5 font-mono text-item text-ink outline-none placeholder:text-faint focus:border-accent"
                />
                <button
                  onClick={() => void handleBarcode({ upc })}
                  disabled={busy !== null || upc.trim().length < 8}
                  className="h-11 flex-none rounded-md border border-line px-4 text-body font-medium text-muted transition-colors hover:border-ink hover:text-ink disabled:opacity-40"
                >
                  {busy === "barcode" ? "Looking up…" : "Look up"}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex-none">
                <ErrorNote>{error}</ErrorNote>
              </div>
            )}
          </div>
        </div>
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
          // Stage only. Detection costs real money and takes seconds, so it
          // waits for someone to ask for it.
          if (file) stagePhoto(file);
          e.target.value = "";
        }}
      />
      <input
        ref={barcodeFileRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleBarcode({ image: file });
          e.target.value = "";
        }}
      />
    </>
  );
}
