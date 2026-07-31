import { useState } from "react";
import { type ProductView, ReviewWorkbench } from "./components/ReviewWorkbench";

export function App() {
  const [activeView, setActiveView] = useState<ProductView>("review");
  return <ReviewWorkbench activeView={activeView} onViewChange={setActiveView} />;
}
