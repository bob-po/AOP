declare module "pptx-preview" {
  export type PptxPreviewer = {
    preview: (data: ArrayBuffer) => Promise<void> | void;
    destroy?: () => void;
  };

  export function init(
    el: HTMLElement,
    options?: { width?: number; height?: number },
  ): PptxPreviewer;
}
