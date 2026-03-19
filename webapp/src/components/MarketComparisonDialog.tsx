import { Doc } from "../../../convex/_generated/dataModel";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

interface MarketComparisonDialogProps {
  markets: Doc<"nexusMarkets">[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatPrice(price: number | null | undefined) {
  if (price == null) return "N/A";
  return `${(price * 100).toFixed(1)}%`;
}

function formatVolume(volume: number | null | undefined) {
  if (volume == null) return "N/A";
  return volume.toLocaleString();
}

function platformBadgeClass(platform: string) {
  switch (platform.toLowerCase()) {
    case "kalshi":
      return "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200";
    case "polymarket":
      return "bg-green-300 text-green-800 dark:bg-green-700 dark:text-green-200";
    default:
      return "bg-gray-300 text-gray-800 dark:bg-gray-600 dark:text-gray-200";
  }
}

export function MarketComparisonDialog({
  markets,
  open,
  onOpenChange,
}: MarketComparisonDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[90vw] max-h-[80vh] overflow-y-auto p-6">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold dark:text-white">
            Compare Markets ({markets.length})
          </DialogTitle>
          <DialogDescription>
            Side-by-side comparison of selected markets
          </DialogDescription>
        </DialogHeader>

        {markets.length > 6 && (
          <div className="bg-yellow-100 border-2 border-black rounded p-3 text-sm font-medium dark:bg-yellow-900 dark:text-yellow-200">
            Showing {markets.length} markets. Select fewer for better readability.
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
          {markets.map((market) => (
            <div
              key={market._id}
              className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-4 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]"
            >
              <h4 className="font-bold text-gray-900 dark:text-white text-sm mb-3 line-clamp-2">
                {market.title}
              </h4>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Platform</span>
                  <span className={`px-2 py-0.5 rounded border border-black text-xs font-bold ${platformBadgeClass(market.platform)}`}>
                    {market.platform.charAt(0).toUpperCase() + market.platform.slice(1)}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Price</span>
                  <span className="text-lg font-bold text-gray-900 dark:text-white">
                    {formatPrice(market.lastPrice)}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Volume</span>
                  <span className="font-medium text-gray-700 dark:text-gray-300">
                    {formatVolume(market.lastVolume)}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Category</span>
                  <span className="px-2 py-0.5 rounded border border-black text-xs font-bold bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200">
                    {market.category}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Status</span>
                  <span className={`px-2 py-0.5 rounded border border-black text-xs font-bold ${
                    market.isActive
                      ? "bg-green-300 text-green-800 dark:bg-green-700 dark:text-green-200"
                      : "bg-gray-300 text-gray-600 dark:bg-gray-600 dark:text-gray-400"
                  }`}>
                    {market.isActive ? "Active" : "Inactive"}
                  </span>
                </div>

                <div className="flex items-center justify-between pt-1 border-t border-gray-200 dark:border-gray-600">
                  <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Updated</span>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {new Date(market.syncedAt).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
