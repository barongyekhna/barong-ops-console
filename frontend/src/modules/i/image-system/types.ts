export type ISourceType = "generate" | "edit";

export type IImageCandidate = {
  candidate_id: string;
  source_type: ISourceType;
  status: "GENERATED";
  image_base64: string;
  mime_type: string;
  width: number;
  height: number;
  file_size: number;
  content_sha256: string;
  image_prompt_enhanced: string;
  metadata: Record<string, unknown>;
};

export type IGenerateResponse = {
  event_id: string;
  source_type: "generate";
  image_prompt_enhanced: string;
  lifecycle: string[];
  candidates: IImageCandidate[];
  prompt_provider: string;
};

export type IEditResponse = {
  event_id: string;
  source_type: "edit";
  image_prompt_enhanced: string;
  lifecycle: string[];
  reference_image_count: number;
  candidates: IImageCandidate[];
  prompt_provider: string;
  temp_reference_images_persisted: boolean;
};

export type IMediaAsset = {
  id: string;
  image_id: string;
  product_id: string | null;
  variant_id: string | null;
  source_type: ISourceType;
  origin_context: string;
  status: string;
  media_bucket: string;
  prompt_original: string | null;
  image_prompt_enhanced: string;
  aspect_ratio: string | null;
  filename: string;
  object_key: string;
  file_url: string;
  thumbnail_url: string;
  preview_url: string;
  mime_type: string;
  width: number | null;
  height: number | null;
  file_size: number;
  content_sha256: string;
  metadata_json: Record<string, unknown> | unknown[] | null;
  created_at: string;
  updated_at: string;
};

export type IMediaListResponse = {
  items: IMediaAsset[];
  count: number;
  limit: number;
  offset: number;
};

export type ISaveMediaResponse = {
  items: IMediaAsset[];
  count: number;
};
