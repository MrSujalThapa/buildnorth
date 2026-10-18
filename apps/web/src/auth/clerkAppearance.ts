import type { Theme } from "../theme/theme";

type ClerkAppearance = {
  variables: Record<string, string>;
  elements: Record<string, Record<string, string | number>>;
};

export function clerkAppearance(theme: Theme): ClerkAppearance {
  const dark = theme === "dark";
  return {
    variables: {
      colorPrimary: dark ? "#f3f1ed" : "#161513",
      colorBackground: dark ? "#131314" : "#faf8f5",
      colorText: dark ? "#f3f1ed" : "#161513",
      colorTextSecondary: dark ? "#9b9791" : "#706d68",
      colorTextOnPrimaryBackground: dark ? "#0b0b0c" : "#f4f2ee",
      colorNeutral: dark ? "#9b9791" : "#706d68",
      colorInputBackground: dark ? "#131314" : "#faf8f5",
      colorInputText: dark ? "#f3f1ed" : "#161513",
      colorDanger: dark ? "#e07068" : "#8a352e",
      borderRadius: "10px",
      fontFamily: '"Instrument Sans", "Segoe UI", system-ui, sans-serif',
      fontFamilyButtons: '"Instrument Sans", "Segoe UI", system-ui, sans-serif',
    },
    elements: {
      rootBox: { width: "100%" },
      cardBox: { width: "100%", boxShadow: "none", border: "0" },
      card: {
        boxShadow: "none",
        background: "transparent",
        border: "0",
        padding: "0",
        width: "100%",
      },
      headerTitle: { display: "none" },
      headerSubtitle: { display: "none" },
      header: { display: "none" },
      socialButtonsBlockButton: {
        minHeight: "46px",
        border: dark ? "1px solid #292828" : "1px solid #dfddd8",
        borderRadius: "10px",
        background: dark ? "#131314" : "#faf8f5",
        boxShadow: "none",
        fontWeight: "650",
      },
      formFieldInput: {
        minHeight: "46px",
        borderRadius: "10px",
        boxShadow: "none",
        fontSize: "16px",
      },
      formButtonPrimary: {
        minHeight: "46px",
        borderRadius: "10px",
        boxShadow: "none",
        fontWeight: "650",
        textTransform: "none",
      },
      footer: { background: "transparent" },
      footerAction: { color: dark ? "#9b9791" : "#706d68" },
      identityPreview: { border: "0", boxShadow: "none" },
    },
  };
}
