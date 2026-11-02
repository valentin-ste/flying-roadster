import Foundation
import os

// One line per event: the unified log (Console, `log stream --predicate 'subsystem == "com.valentinste.roadster"'`),
// stderr with --log or --selftest, and a file with -TestLogFile <path> (the move test: the relaunched copy has no terminal).
enum Log {
    private static let logger = Logger(subsystem: "com.valentinste.roadster", category: "app")
    private static let t0 = Date()
    private static let echo = CommandLine.arguments.contains("--log") || CommandLine.arguments.contains("--selftest")
    private static let file: FileHandle? = {
        guard let p = UserDefaults.standard.string(forKey: "TestLogFile") else { return nil }
        if !FileManager.default.fileExists(atPath: p) { FileManager.default.createFile(atPath: p, contents: nil) }
        let h = FileHandle(forWritingAtPath: p)
        h?.seekToEndOfFile()
        return h
    }()

    static func say(_ s: String) {
        logger.log("\(s, privacy: .public)")
        let line = String(format: "[%7.3f] ", Date().timeIntervalSince(t0)) + s + "\n"
        if echo { FileHandle.standardError.write(line.data(using: .utf8)!) }
        if let file { file.write(("pid \(ProcessInfo.processInfo.processIdentifier) " + line).data(using: .utf8)!) }
    }
}
