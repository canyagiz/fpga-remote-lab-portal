// "In partnership with" list shown on the landing page.
//
// LICENSE (Branding & Attribution Requirement, item 2): entries already in
// this list when you obtained the Software may not be removed or hidden.
// Deployers may APPEND their own institution below - do not delete or
// reorder existing entries.
export interface Partner {
  name: string;
  url: string;
  logo: string;
  logoClassName?: string;
}

export const partners: Partner[] = [
  {
    name: "Hochschule Bonn-Rhein-Sieg",
    url: "https://www.h-brs.de/de",
    logo: "/bonn-logo.png",
    logoClassName: "h-20 w-auto",
  },
  // Add your institution's entry below this line. Do not remove the entry above.
];
