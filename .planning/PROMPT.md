# Azure Agentic Platform (AAP) — Prompts for Development

> Version: 1.0 | Date: 2026-04-12

---

## Prompts

- Review current system's capabiliities, identify gaps, overlaps and areas of enhancements and create the roadmap. Do it autonomously and whatever you deem fit to achieve a world class aiops platform. Always follow the architecture design in @ARCHITECTURE.md, focus on current codebase and not build standalone modules that's not aligned to the design. Revamp or enhance whenever necessary including architecture design but ensure nothing is broken. When solving problems, don't take the easiest way out and cut corners, always perform impact analysis of the solution and alignment to the architecture design. If additional phases needs to be added to the roadmap, do it without asking for permissions. For every phase completion, commit, push and merge by creating PR and ensure there are no problems in GitHub actions before proceeding to the next phase. Make sure everything is documented and updated in the respective MD files.   

- Test all tabs and its sub-tabs using ralph-loop and playwright-skill at https://ca-web-ui-prod.wittypebble-0144adc3.eastus2.azurecontainerapps.io/. For pages or sections of the page that shows up blank, 0 or empty values, etc., document it in tab-issues.md. Clear context after every tab and sub-tab.

- Use ralph-loop and playwright-skill to fix and test all the issues in @tab-issues.md. Update @tab-issues.md on the progress so that we can track.