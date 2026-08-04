// Request-scoped fetches shared by the project layout, its tabs, and their
// generateMetadata — cache() dedupes so each renders from one API call.
import { cache } from "react";
import { api } from "@/lib/api";

export const getProject = cache((slug: string) => api.developmentProject(slug));
export const getWiki = cache((slug: string) => api.developmentWiki(slug));
export const getEvaluation = cache((slug: string) => api.developmentEvaluation(slug));
