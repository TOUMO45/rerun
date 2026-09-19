import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Intake } from "./screens/Intake";
import { RunTimeline } from "./screens/RunTimeline";
import { Certificate } from "./screens/Certificate";
import { BatchLab } from "./screens/BatchLab";

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Intake />} />
        <Route path="/runs/:runId" element={<RunTimeline />} />
        <Route path="/runs/:runId/certificate" element={<Certificate />} />
        <Route path="/batch" element={<BatchLab />} />
      </Routes>
    </Shell>
  );
}
