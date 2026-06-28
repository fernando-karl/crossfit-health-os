import Foundation
import HealthKit

enum HealthKitError: LocalizedError {
    case unavailable
    case unauthorized
    case noData

    var errorDescription: String? {
        switch self {
        case .unavailable: return "HealthKit indisponível neste dispositivo"
        case .unauthorized: return "Permissão Health negada"
        case .noData: return "Nenhuma métrica recente no Apple Health"
        }
    }
}

final class HealthKitManager {
    private let store = HKHealthStore()

    private var hrvType: HKQuantityType? {
        HKQuantityType.quantityType(forIdentifier: .heartRateVariabilitySDNN)
    }

    private var rhrType: HKQuantityType? {
        HKQuantityType.quantityType(forIdentifier: .restingHeartRate)
    }

    private var sleepType: HKCategoryType? {
        HKCategoryType.categoryType(forIdentifier: .sleepAnalysis)
    }

    func requestAuthorization() async throws {
        guard HKHealthStore.isHealthDataAvailable() else { throw HealthKitError.unavailable }

        var readTypes = Set<HKObjectType>()
        if let hrvType { readTypes.insert(hrvType) }
        if let rhrType { readTypes.insert(rhrType) }
        if let sleepType { readTypes.insert(sleepType) }

        try await store.requestAuthorization(toShare: [], read: readTypes)
    }

    func buildDailyPayload() async throws -> [String: Any] {
        let calendar = Calendar.current
        let startOfDay = calendar.startOfDay(for: Date())
        let end = Date()

        async let hrv = latestHRV(since: startOfDay, until: end)
        async let rhr = latestRHR(since: calendar.date(byAdding: .day, value: -1, to: startOfDay)!, until: end)
        async let sleep = sleepSummary(since: calendar.date(byAdding: .day, value: -1, to: startOfDay)!, until: end)

        let (hrvMs, hrvDate) = try await hrv
        let (rhrBpm, _) = try await rhr
        let (sleepHours, sleepQuality, sleepStart) = try await sleep

        guard hrvMs != nil || rhrBpm != nil || sleepHours != nil else {
            throw HealthKitError.noData
        }

        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]

        var payload: [String: Any] = [
            "type": "daily_recovery",
            "device": "iPhone",
            "start_date": iso.string(from: sleepStart ?? hrvDate ?? startOfDay),
            "end_date": iso.string(from: end),
        ]

        if let hrvMs { payload["hrv_rmssd_ms"] = hrvMs }
        if let rhrBpm { payload["resting_heart_rate_bpm"] = rhrBpm }
        if let sleepHours { payload["sleep_duration_hours"] = sleepHours }
        if let sleepQuality { payload["sleep_quality_score"] = sleepQuality }

        return payload
    }

    private func latestHRV(since: Date, until: Date) async throws -> (Int?, Date?) {
        guard let type = hrvType else { return (nil, nil) }

        return try await withCheckedThrowingContinuation { continuation in
            let predicate = HKQuery.predicateForSamples(withStart: since, end: until)
            let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
            let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: 1, sortDescriptors: [sort]) { _, samples, error in
                if let error { continuation.resume(throwing: error); return }
                guard let sample = samples?.first as? HKQuantitySample else {
                    continuation.resume(returning: (nil, nil)); return
                }
                let ms = Int(sample.quantity.doubleValue(for: HKUnit.secondUnit(with: .milli)))
                continuation.resume(returning: (ms, sample.endDate))
            }
            store.execute(query)
        }
    }

    private func latestRHR(since: Date, until: Date) async throws -> (Int?, Date?) {
        guard let type = rhrType else { return (nil, nil) }

        return try await withCheckedThrowingContinuation { continuation in
            let predicate = HKQuery.predicateForSamples(withStart: since, end: until)
            let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
            let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: 1, sortDescriptors: [sort]) { _, samples, error in
                if let error { continuation.resume(throwing: error); return }
                guard let sample = samples?.first as? HKQuantitySample else {
                    continuation.resume(returning: (nil, nil)); return
                }
                let bpm = Int(sample.quantity.doubleValue(for: HKUnit.count().unitDivided(by: .minute())))
                continuation.resume(returning: (bpm, sample.endDate))
            }
            store.execute(query)
        }
    }

    private func sleepSummary(since: Date, until: Date) async throws -> (Double?, Int?, Date?) {
        guard let type = sleepType else { return (nil, nil, nil) }

        return try await withCheckedThrowingContinuation { continuation in
            let predicate = HKQuery.predicateForSamples(withStart: since, end: until)
            let sort = NSSortDescriptor(key: HKSampleSortIdentifierEndDate, ascending: false)
            let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: [sort]) { _, samples, error in
                if let error { continuation.resume(throwing: error); return }
                guard let samples = samples as? [HKCategorySample], !samples.isEmpty else {
                    continuation.resume(returning: (nil, nil, nil)); return
                }

                let asleepValues: Set<Int> = [
                    HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue,
                    HKCategoryValueSleepAnalysis.asleepCore.rawValue,
                    HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
                    HKCategoryValueSleepAnalysis.asleepREM.rawValue,
                ]

                var asleepSeconds: TimeInterval = 0
                var deepSeconds: TimeInterval = 0
                var remSeconds: TimeInterval = 0
                var earliestStart: Date?

                for sample in samples {
                    guard asleepValues.contains(sample.value) else { continue }
                    let duration = sample.endDate.timeIntervalSince(sample.startDate)
                    asleepSeconds += duration
                    if earliestStart == nil || sample.startDate < earliestStart! {
                        earliestStart = sample.startDate
                    }
                    if sample.value == HKCategoryValueSleepAnalysis.asleepDeep.rawValue {
                        deepSeconds += duration
                    } else if sample.value == HKCategoryValueSleepAnalysis.asleepREM.rawValue {
                        remSeconds += duration
                    }
                }

                guard asleepSeconds > 0 else {
                    continuation.resume(returning: (nil, nil, nil)); return
                }

                let hours = asleepSeconds / 3600.0
                // Heuristic quality 0–100 from deep+REM share
                let restorative = deepSeconds + remSeconds
                let quality = min(100, max(0, Int((restorative / asleepSeconds) * 100)))

                continuation.resume(returning: (hours, quality, earliestStart))
            }
            store.execute(query)
        }
    }
}
