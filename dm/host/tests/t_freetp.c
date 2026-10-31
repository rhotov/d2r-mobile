// 免费回城绑定回归：用合成 HUD 快照、面键映射 main+0x2d13cbc 与技能槽 main+0x2d5f0c0 的内存模型验证实际选中组；不运行游戏映像。
// Free portal binding regression: synthetic HUD snapshots and memory models of mapping main+0x2d13cbc and slots main+0x2d5f0c0 verify the selected bank; no game image is run.
#include "../dm_freetp.c"
#include <assert.h>
static dm_tg_snapshot state;
static uint64_t tick = 100;
uint64_t now_ns(void) { return tick; }
int dm_touch_game_snapshot(dm_tg_snapshot *s) { *s = state; return state.valid; }
int main(void) {
    uint8_t *mb = calloc(1, 0x2d5f0c0 + 32 * 28);
    uint8_t pl[0x200] = {0}; /* 版本 0 跳过原版技能授予。 | Version 0 skips native skill grant. */
    assert(mb);
    uint32_t mapping[] = {0x800, 5, 11};
    memcpy(mb + 0x2d13cbc, mapping, sizeof mapping);
    memset(mb + 0x2d5f0c0, 0xff, 32 * 28);
    uint32_t skill = 42;
    memcpy(mb + 0x2d5f0c0 + 5 * 28, &skill, 4);
    state.valid = state.ready = 1; state.captured_ns = tick;
    dm_freetp_client_step(mb, (uint64_t)pl);
    assert(!dm_freetp_zr_free(0)); /* 当前组已绑定，未使用组为空。 | Active binding, unused bank empty. */
    assert(dm_freetp_zr_free(1));
    state.selected_bank = 16;
    dm_freetp_client_step(mb, (uint64_t)pl);
    assert(dm_freetp_zr_free(0));
    memcpy(mb + 0x2d5f0c0 + 21 * 28, &skill, 4);
    dm_freetp_client_step(mb, (uint64_t)pl);
    assert(!dm_freetp_zr_free(0));
    state.ready = 0;
    dm_freetp_client_step(mb, (uint64_t)pl);
    assert(!dm_freetp_zr_free(1));
    state.ready = 1; tick += DM_TG_MAX_AGE_NS + 1;
    dm_freetp_client_step(mb, (uint64_t)pl);
    assert(!dm_freetp_zr_free(1));
    dm_freetp_client_step(mb, 0);
    assert(!dm_freetp_zr_free(0));
    free(mb); puts("freetp binding checks passed");
}
