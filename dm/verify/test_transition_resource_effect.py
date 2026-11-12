# 用改写后的 main.patched.bin 核对换图时资源缺失和粒子状态异常的处理。
# Run against the generated main.patched.bin to check missing resources and particle state after area changes.
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2

from nsoimg import header


RESOURCE_RELEASE = 0x1328B24
RESOURCE_SLOT_RELOAD = 0x1328BE8
EFFECT_IS_RUNNING = 0x144F170
PAGE_SIZE = 0x1000
DATA = 0x10000000
RETURN = DATA + 0xF000


def make_machine(image, patch_offset, entry):
    machine = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    code_page = entry & -PAGE_SIZE
    machine.mem_map(code_page, PAGE_SIZE)
    machine.mem_write(code_page, image[code_page:code_page + PAGE_SIZE])
    patch = image[patch_offset:]
    machine.mem_map(patch_offset, (len(patch) + PAGE_SIZE - 1) & -PAGE_SIZE)
    machine.mem_write(patch_offset, patch)
    machine.mem_map(DATA, 0x10000)
    machine.reg_write(UC_ARM64_REG_SP, RETURN)
    machine.reg_write(UC_ARM64_REG_LR, RETURN)
    return machine


def run(machine, entry, arg0, arg1, arg2=0):
    machine.reg_write(UC_ARM64_REG_X0, arg0)
    machine.reg_write(UC_ARM64_REG_X1, arg1)
    machine.reg_write(UC_ARM64_REG_X2, arg2)
    machine.emu_start(entry, RETURN, count=3000)
    assert machine.reg_read(UC_ARM64_REG_PC) == RETURN, f"{entry:#x} did not return"


def write(machine, address, fmt, *values):
    machine.mem_write(address, struct.pack("<" + fmt, *values))


def release_resources(image, patch_offset, *, both_counts, has_table=True, slot_update=None):
    machine = make_machine(image, patch_offset, RESOURCE_RELEASE)
    context, args, ids, entry = (DATA + offset for offset in (0x100, 0x400, 0x500, 0x700))
    table, page = DATA + 0x800, DATA + 0x1000
    valid, empty_slot, empty_page, outside_table = 0x201, 0x202, 0xB71, 0xC01
    resource_ids = (valid, valid, empty_slot, empty_page, outside_table, valid)
    if slot_update:
        resource_ids = (valid,)
    write(machine, args, "QI", ids, len(resource_ids))
    write(machine, ids, f"{len(resource_ids)}I", *resource_ids)
    write(machine, context + 0x1A0, "Q", table if has_table else 0)
    write(machine, context + 0x1B0, "I", 6)
    # 崩溃现场第 5 页为空；第 6 页有指针但超出了表的声明范围。
    # Page 5 was null in the crash. Page 6 has a pointer but lies outside the declared table.
    write(machine, table, "7Q", 0, page, 0, 0, 0, 0, page)
    write(machine, page + 8, "Q", entry)
    write(machine, entry + 0x88, "II", 17, 23)
    replacement = DATA + 0x900
    if slot_update:
        write(machine, replacement + 0x88, "II", 31, 37)

        def update_slot(uc, *_):
            write(uc, page + 8, "Q", replacement if slot_update == "replace" else 0)

        machine.hook_add(UC_HOOK_CODE, update_slot, begin=RESOURCE_SLOT_RELOAD, end=RESOURCE_SLOT_RELOAD)

    run(machine, RESOURCE_RELEASE, context, args, both_counts)

    expected = (14, 20 if both_counts else 23) if has_table else (17, 23)
    if slot_update:
        expected = (17, 22)
        replacement_counts = struct.unpack("<II", machine.mem_read(replacement + 0x88, 8))
        assert replacement_counts == (31, 37), (slot_update, replacement_counts)
    counts = struct.unpack("<II", machine.mem_read(entry + 0x88, 8))
    assert counts == expected, (both_counts, has_table, slot_update, counts)


def check_effect(image, patch_offset, ids, expected, *, constant=False, has_state=True, has_context=True):
    machine = make_machine(image, patch_offset, EFFECT_IS_RUNNING)
    output, args, source, context = (DATA + offset for offset in (0x100, 0x200, 0x300, 0x400))
    indices, result, state = (DATA + offset for offset in (0x500, 0x600, 0x700))
    write(machine, output, "QII", result, len(expected), 4)
    write(machine, args + 8, "Q", source)
    write(machine, source + 0x10, "QQ", context if has_context else 0, indices)
    write(machine, source + 0x28, "I", ids[0] if constant else 0xFFFFFFFF)
    write(machine, indices, f"{len(ids)}I", *ids)
    write(machine, context + 0x48, "QII", state if has_state else 0, 3, 8)
    # 第四个字节在容量内，但超过当前元素数。
    # The fourth byte is outside the current element count but inside capacity.
    write(machine, state, "4B", 0x80, 0x7F, 0xFF, 0x80)
    sentinel = b"\xa5" * 4
    machine.mem_write(result - 4, sentinel * (len(expected) + 2))

    run(machine, EFFECT_IS_RUNNING, output, args)

    actual = bytes(machine.mem_read(result - 4, (len(expected) + 2) * 4))
    assert actual == sentinel + struct.pack(f"<{len(expected)}i", *expected) + sentinel, (ids, actual.hex())


if __name__ == "__main__":
    path = Path(sys.argv[1])
    image = path.read_bytes()
    patch_offset = header(path.parent, "main")["PATCH_OFF"]
    for both_counts in (False, True):
        for has_table in (False, True):
            release_resources(image, patch_offset, both_counts=both_counts, has_table=has_table)
    for slot_update in ("clear", "replace"):
        release_resources(image, patch_offset, both_counts=True, slot_update=slot_update)

    check_effect(image, patch_offset, (0,), (-1,) * 9, constant=True)
    check_effect(image, patch_offset, (3,), (0,) * 9, constant=True)
    check_effect(image, patch_offset, (0,), (0,) * 3, constant=True, has_state=False)
    check_effect(image, patch_offset, (3, 0, 1, 2, 3), (0, -1, 0, -1, 0))
    check_effect(image, patch_offset, (0x46BC695D, 0, 2, 0), (0, -1, -1, -1))
    check_effect(image, patch_offset, (0, 1, 2), (0, 0, 0), has_state=False)
    check_effect(image, patch_offset, (0, 2), (0, 0), has_context=False)
    print("Transition resource release and particle state OK (13 cases)")
