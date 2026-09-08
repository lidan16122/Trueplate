import type { FoodDetectionResponse } from "@/types/detection";

import { post, request } from "@/services/http";

export const detectionApi = {
    /** Multipart, so `request` omits the JSON Content-Type and lets fetch set the boundary. */
    detectPhoto: (image: File, note?: string) => {
      const body = new FormData();
      body.append("image", image);
      // A caption is not a hint — a quantity stated here overrides the visual
      // estimate entirely, so it goes up with the photo rather than being
      // applied afterwards.
      if (note?.trim()) body.append("note", note.trim());
      return request<FoodDetectionResponse>("/ai/detect/photo", { method: "POST", body });
    },
    detectText: (description: string) =>
      post<FoodDetectionResponse>("/ai/detect/text", { description }),
    /**
     * Either shape: the phone posts the photo it captured and the server
     * decodes the UPC, the desktop posts the digits the user typed. Multipart
     * for both, because one endpoint cannot accept JSON and a file.
     */
    detectBarcode: (input: { image?: File; upc?: string }) => {
      const body = new FormData();
      if (input.image) body.append("image", input.image);
      if (input.upc?.trim()) body.append("upc", input.upc.trim());
      return request<FoodDetectionResponse>("/ai/detect/barcode", { method: "POST", body });
    },
  };
