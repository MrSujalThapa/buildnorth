import SettingsPage from "../components/utility/SettingsPage";
import { useTheme } from "../theme/useTheme";

export function SettingsRoute() {
  const { theme, setTheme } = useTheme();
  const resolved = theme === "dark" ? "dark" : "light";
  return <SettingsPage theme={resolved} onSetTheme={setTheme} />;
}
