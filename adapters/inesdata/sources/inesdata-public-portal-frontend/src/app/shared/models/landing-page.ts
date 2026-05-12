import { CatalogBlock } from "./catalog-block";
import { GetToKnowUsBlock } from "./get-to-know-us-block";
import { JoinBlock } from "./join-block";
import { WelcomeBlock } from "./welcome-block";

export interface LandingPage {
	title: String,
	welcomeBlock: WelcomeBlock,
	catalogBlock: CatalogBlock,
	getToKnowUsBlock: GetToKnowUsBlock,
	joinBlock: JoinBlock
}
