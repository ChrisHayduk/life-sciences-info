import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      {/* Hero skeleton */}
      <div className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg">
        <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr] lg:items-end">
          <div className="space-y-3">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-96 max-w-full" />
            <Skeleton className="h-4 w-80 max-w-full" />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="border-border/50">
                <CardContent className="p-4 space-y-2">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-7 w-12" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
      {/* Cards skeleton */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-48" />
          </div>
          <CardSkeleton />
          <CardSkeleton />
        </div>
        <div className="space-y-4">
          <div className="space-y-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-6 w-40" />
          </div>
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    </div>
  );
}

export function CardSkeleton() {
  return (
    <Card className="border-border/50">
      <CardHeader className="p-5 pb-3 space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-3 w-24" />
        </div>
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-3 w-1/3" />
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
      </CardContent>
    </Card>
  );
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-6 w-48" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex gap-4 items-center py-3 border-b border-border/30">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-32" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg space-y-4">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-8 w-96 max-w-full" />
        <Skeleton className="h-4 w-64" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-28 rounded-full" />
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-6 w-24 rounded-full" />
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-4/6" />
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardContent className="p-6 space-y-3">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-6 w-36" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function CardsGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border/50 bg-card p-7 shadow-lg space-y-3">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-80 max-w-full" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: count }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
