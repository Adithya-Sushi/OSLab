import Foundation
import Virtualization

// A small headless launcher. All disks and the sole writable directory share
// are explicitly supplied project paths. No host device is passed through.
final class Delegate: NSObject, VZVirtualMachineDelegate {
    func guestDidStop(_ virtualMachine: VZVirtualMachine) { exit(0) }
    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        fputs("VM stopped: \(error)\n", stderr); exit(2)
    }
}
guard CommandLine.arguments.count == 4 else {
    fputs("usage: oslab-vm ROOT_DISK SEED_DISK PROJECT_DIRECTORY\n", stderr); exit(2)
}
let diskURL = URL(fileURLWithPath: CommandLine.arguments[1])
let seedURL = URL(fileURLWithPath: CommandLine.arguments[2])
let shareURL = URL(fileURLWithPath: CommandLine.arguments[3])
let storeURL = diskURL.deletingLastPathComponent().appendingPathComponent("nvram.efi")
let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = 2
configuration.memorySize = 3 * 1024 * 1024 * 1024
let bootLoader = VZEFIBootLoader()
do {
    if FileManager.default.fileExists(atPath: storeURL.path) {
        bootLoader.variableStore = VZEFIVariableStore(url: storeURL)
    } else {
        bootLoader.variableStore = try VZEFIVariableStore(creatingVariableStoreAt: storeURL)
    }
    configuration.bootLoader = bootLoader
    let platform = VZGenericPlatformConfiguration()
    let identityURL = diskURL.deletingLastPathComponent().appendingPathComponent("machine-id.bin")
    if let data = try? Data(contentsOf: identityURL), let identity = VZGenericMachineIdentifier(dataRepresentation: data) {
        platform.machineIdentifier = identity
    } else {
        try platform.machineIdentifier.dataRepresentation.write(to: identityURL)
    }
    configuration.platform = platform
    let root = VZVirtioBlockDeviceConfiguration(attachment: try VZDiskImageStorageDeviceAttachment(url: diskURL, readOnly: false))
    let seed = VZVirtioBlockDeviceConfiguration(attachment: try VZDiskImageStorageDeviceAttachment(url: seedURL, readOnly: true))
    configuration.storageDevices = [root, seed]
    let network = VZVirtioNetworkDeviceConfiguration()
    network.attachment = VZNATNetworkDeviceAttachment()
    configuration.networkDevices = [network]
    let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
    serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: FileHandle.standardInput, fileHandleForWriting: FileHandle.standardOutput)
    configuration.serialPorts = [serial]
    configuration.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
    let share = VZVirtioFileSystemDeviceConfiguration(tag: "oslab")
    share.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: shareURL, readOnly: false))
    configuration.directorySharingDevices = [share]
    try configuration.validate()
} catch { fputs("VM configuration: \(error)\n", stderr); exit(2) }
let delegate = Delegate()
let machine = VZVirtualMachine(configuration: configuration)
machine.delegate = delegate
machine.start { result in
    switch result {
    case .success: fputs("OSLAB_VM_STARTED ram=3GiB vcpus=2 backend=AppleVirtualization\n", stderr)
    case .failure(let error): fputs("VM start: \(error)\n", stderr); exit(2)
    }
}
RunLoop.main.run()
