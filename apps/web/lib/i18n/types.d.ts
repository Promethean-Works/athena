import "i18next"

import type en from "@/locales/en"

// Makes t("namespace:key") check against the English files: a typo fails typecheck.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common"
    resources: typeof en
  }
}
