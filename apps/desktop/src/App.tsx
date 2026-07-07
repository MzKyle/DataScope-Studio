import { StudioWorkspace } from "./features/studio/StudioWorkspace";

export {
  GlobalErrorToast,
  InlineError,
  MappingIssueCard,
  clearErrorAreaState,
  ErrorDialog,
  defaultOutputName,
  sourceFileDialogFilters,
  sourceFileExtensions
} from "./app-support";
export type { AreaErrors, ErrorDialogRequest, ErrorArea } from "./app-support";

export default function App() {
  return <StudioWorkspace />;
}
