import { Composition } from "remotion";
import { Explainer } from "./Explainer";

// 15 s @ 30 fps. 1280×720 keeps the README GIF light; the MP4 is crisp.
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Explainer"
      component={Explainer}
      durationInFrames={450}
      fps={30}
      width={1280}
      height={720}
    />
  );
};
