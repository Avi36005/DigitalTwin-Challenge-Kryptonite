/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_GLUCOTWIN_TRANSPORT?: "fixtures" | "http";
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
