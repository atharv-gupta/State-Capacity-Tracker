import "./globals.css";

export const metadata = {
  title: "State Capacity Tracker",
  description: "What state governments are actually doing, in Recoding America's capacities",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
