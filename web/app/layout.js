import "./globals.css";

export const metadata = {
  title: "State Capacity Tracker",
  description: "What governments are doing in the world of state capacity",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
