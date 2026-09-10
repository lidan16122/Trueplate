import { ApiError } from "@/services/http";
import { profileApi } from "@/services/profile";
import type { FoodDetectionResponse } from "@/types/detection";
import type { PromptLimit } from "@/types/profile";
import { today } from "@/utils/format";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { detectionApi } from "../services/detection";


type Mode = "idle" | "text" | "barcode";

/** Owns staged uploads and hands preview URL ownership to confirmation only after detection succeeds. */
export function useAddFood() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const date = params.get("date") ?? today();

  const cameraFileRef = useRef<HTMLInputElement>(null);
  const galleryFileRef = useRef<HTMLInputElement>(null);
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

  // The account's remaining AI allowance. Fetched on mount rather than held in
  // context: it only moves when entries are saved from the confirm screen,
  // which navigates back through here.
  //
  // Null — unanswered, or a failed check — counts as allowed. Blocking on the
  // round trip would grey the camera out for a beat on every visit, and the
  // detect routes refuse an over-cap request themselves, so the worst a wrong
  // guess costs is one 403 the user sees as an error.
  const [limit, setLimit] = useState<PromptLimit | null>(null);
  useEffect(() => {
    void profileApi
      .userLimit()
      .then(setLimit)
      .catch(() => setLimit(null));
  }, []);

  const aiBlocked = limit !== null && !limit.allowed;
  // Barcode is exempt everywhere below: it calls no model, so it costs nothing
  // against the cap and stays the one way a capped user can still log a meal.
  const capNote = `You have used all ${limit?.limit ?? 0} AI detections on this account. Barcode lookup still works.`;

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
  const stagePhoto = useCallback(
    (file: File) => {
      // File pickers and drops share one photo slot, including while a request
      // is pending so its preview cannot be replaced by a later selection.
      if (aiBlocked || busy !== null) return;
      setError(null);
      setPhotoFile(file);
      // A photo selected from barcode mode needs its preview visible; text mode
      // stays open so an existing note can still be edited alongside the photo.
      setMode((current) => (current === "barcode" ? "idle" : current));
      // Replacing an earlier pick needs nothing extra: the effect above releases
      // the previous object URL when this value changes.
      setPreview(URL.createObjectURL(file));
    },
    [aiBlocked, busy],
  );

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
      goToConfirm(await detectionApi.detectPhoto(photoFile, description), preview);
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
      goToConfirm(await detectionApi.detectText(description), null);
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
        goToConfirm(await detectionApi.detectBarcode(input), null);
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
  return {
    navigate,
    date,
    cameraFileRef,
    galleryFileRef,
    barcodeFileRef,
    mode,
    setMode,
    description,
    setDescription,
    upc,
    setUpc,
    busy,
    error,
    preview,
    photoFile,
    dragging,
    setDragging,
    aiBlocked,
    capNote,
    stagePhoto,
    clearPhoto,
    submitPhoto,
    handleText,
    handleBarcode,
    onDrop,
  };
}
