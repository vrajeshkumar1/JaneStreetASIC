// SPDX-FileCopyrightText: (c) 2026 Vrajesh Kumar
// SPDX-License-Identifier: MIT
//
// One protocol engine. Implements the instruction set in docs/spec.md, part 1.
//
// The program memory is outside this module (an IHP memory block with a
// registered read). The engine presents the address of the next instruction on
// the same clock on which the current one completes, so the next instruction
// is on mem_dout_i one clock later and no tick is lost on a jump.
//
// Naming: *_q is a flip-flop output, *_d is its next value, *_i / *_o are ports.

`default_nettype none

module pe_engine #(
    parameter int unsigned AW      = 8,    // program address width (256 words)
    parameter int unsigned FIFO_AW = 4,    // each FIFO holds 2**FIFO_AW bytes (at most 4)
    parameter int unsigned DM_AW   = 4,    // the data memory holds 2**DM_AW bytes (at most 4)
    parameter bit          HAS_CRC    = 1'b1,  // 0 = no checksum unit: crc reads as zero
    parameter bit          HAS_BSHIFT = 1'b1,  // 0 = shl / shr always shift by one place
    parameter bit          HOST_RB    = 1'b1   // 0 = the host cannot read r0..r7 or the data memory
) (
    input  wire         clk,
    input  wire         rst_ni,

    // ---- control
    input  wire         enable_i,          // 1 = run
    input  wire         restart_i,         // pulse: clear pc, shift registers, flags, FIFOs

    // ---- settings (held steady while the engine runs)
    input  wire [15:0]  cfg_clkdiv_i,      // tick = cfg_clkdiv_i + 1 clocks
    input  wire         cfg_out_dir_i,     // 0 = lowest bit first
    input  wire         cfg_in_dir_i,
    input  wire         cfg_autopull_i,
    input  wire         cfg_autopush_i,
    input  wire [3:0]   cfg_pull_thresh_i, // 1..8
    input  wire [3:0]   cfg_push_thresh_i, // 1..8
    input  wire [5:0]   cfg_side0_i,       // [3:0] pin, [4] enable, [5] 1 = direction
    input  wire [5:0]   cfg_side1_i,
    input  wire         cfg_crc_dir_i,     // 0 = lowest bit first
    input  wire [31:0]  cfg_crc_poly_i,
    input  wire [5:0]   cfg_crc_width_i,   // 1..32, used when cfg_crc_dir_i = 1

    // ---- pins
    input  wire [15:0]  pins_i,            // synchronized. [7:0] input pins, [15:8] bidirectional pins
    output wire [15:0]  pin_level_o,       // [7:0] output pins, [15:8] bidirectional pins
    output wire [7:0]   pin_dir_o,         // bidirectional pins: 1 = output

    // ---- shared flags
    input  wire [7:0]   flags_i,
    output logic [7:0]  flag_set_o,
    output logic [7:0]  flag_clr_o,

    // ---- program memory
    output wire          mem_ren_o,
    output wire [AW-1:0] mem_addr_o,
    output wire          mem_wen_o,          // "stm": store one byte
    output wire [31:0]   mem_din_o,
    output wire [31:0]   mem_bm_o,           // which bits of the word to store
    input  wire [31:0]   mem_dout_i,

    // ---- host side of the FIFOs
    input  wire         tx_push_i,
    input  wire [7:0]   tx_data_i,
    output wire         tx_full_o,
    output wire         tx_empty_o,
    output wire [4:0]   tx_level_o,
    input  wire         rx_pop_i,
    output wire [7:0]   rx_data_o,
    output wire         rx_empty_o,
    output wire         rx_full_o,
    output wire [4:0]   rx_level_o,

    // ---- host access to the data memory
    input  wire         dm_we_i,
    input  wire [3:0]   dm_addr_i,
    input  wire [7:0]   dm_wdata_i,
    output wire [7:0]   dm_rdata_o,

    // ---- host access to the registers and the program counter
    input  wire         hreg_we_i,
    input  wire [2:0]   hreg_sel_i,
    input  wire         hreg_hi_i,         // 0 = low byte of the register, 1 = high byte
    input  wire [7:0]   hreg_wdata_i,
    output wire [15:0]  hreg_rdata_o,
    input  wire         pc_we_i,
    input  wire [AW-1:0] pc_wdata_i,
    output wire [AW-1:0] pc_o,

    // ---- status
    output wire         stalled_o,
    output wire         halted_o,
    output wire         illegal_o,
    output wire [1:0]   debug_o,           // [0] pull found FIFO empty, [1] push found it full
    input  wire [1:0]   dbg_clr_i,         // host clears the matching debug_o bit
    output wire [31:0]  crc_o
);

  // ------------------------------------------------------------- opcodes
  localparam logic [3:0] OP_JMP  = 4'd0;
  localparam logic [3:0] OP_JBIT = 4'd1;
  localparam logic [3:0] OP_WAIT = 4'd2;
  localparam logic [3:0] OP_IN   = 4'd3;
  localparam logic [3:0] OP_OUT  = 4'd4;
  localparam logic [3:0] OP_PP   = 4'd5;
  localparam logic [3:0] OP_MOV  = 4'd6;
  localparam logic [3:0] OP_IRQ  = 4'd7;
  localparam logic [3:0] OP_SET  = 4'd8;
  localparam logic [3:0] OP_ALUR = 4'd9;
  localparam logic [3:0] OP_ALUI = 4'd10;
  localparam logic [3:0] OP_LD   = 4'd11;
  localparam logic [3:0] OP_ST   = 4'd12;
  localparam logic [3:0] OP_CALL = 4'd13;
  localparam logic [3:0] OP_PIN  = 4'd14;
  localparam logic [3:0] OP_HALT = 4'd15;

  // --------------------------------------------------------------- state
  logic [AW-1:0] pc_q, pc_d, lr_q, lr_d;
  logic [127:0]  r_q;                 // r0..r7, 16 bits each
  logic [7:0]    isr_q, isr_d, osr_q, osr_d;
  logic [3:0]    isr_cnt_q, isr_cnt_d, osr_cnt_q, osr_cnt_d;
  logic          t_q, t_d, z_q, z_d, c_q, c_d;
  logic [15:0]   wtime_q, wtime_d;
  logic [1:0]    snap_q, snap_d;      // pin values at the start of a "wait change"
  logic          stall_q, stall_d;    // the current instruction has already been tried
  logic          apwait_q, apwait_d;  // an "in" has shifted and is waiting to store
  logic [15:0]   level_q, level_d;
  logic [7:0]    dir_q, dir_d;
  logic [31:0]   crc_q, crc_d;
  wire  [(8<<DM_AW)-1:0] dm_q;        // data memory, 2**DM_AW bytes (latches)
  logic [3:0]    delay_q, delay_d;
  logic          halted_q, halted_d, illegal_q, illegal_d;
  logic [1:0]    dbg_q, dbg_d;
  logic          ir_valid_q;
  // "ldm" / "stm" (a byte in the memory block) take two ticks. On the second,
  // mem_dout_i carries the data word and not an instruction; these remember
  // what the instruction asked for.
  logic          mphase_q;            // second tick of ldm / stm
  logic          m_load_q;            // it is ldm
  logic [2:0]    m_rd_q;              // ldm: destination register
  logic [1:0]    m_byte_q;            // ldm: which byte of the word
  logic [3:0]    m_dly_q;             // the instruction's delay field
  logic [15:0]   div_q;

  // ---------------------------------------------------------------- FIFOs
  logic       tx_pop, rx_push;
  logic [7:0] rx_push_data;
  wire  [7:0] tx_head;

  wire  [FIFO_AW:0] tx_level, rx_level;

  pe_fifo #(.AW(FIFO_AW)) u_tx (
      .clk(clk), .rst_ni(rst_ni), .clear_i(restart_i),
      .push_i(tx_push_i), .wdata_i(tx_data_i),
      .pop_i(tx_pop), .rdata_o(tx_head),
      .empty_o(tx_empty_o), .full_o(tx_full_o), .level_o(tx_level)
  );

  pe_fifo #(.AW(FIFO_AW)) u_rx (
      .clk(clk), .rst_ni(rst_ni), .clear_i(restart_i),
      .push_i(rx_push), .wdata_i(rx_push_data),
      .pop_i(rx_pop_i), .rdata_o(rx_data_o),
      .empty_o(rx_empty_o), .full_o(rx_full_o), .level_o(rx_level)
  );

  // The level ports are five bits wide whatever the FIFO depth.
  logic [4:0] tx_level5, rx_level5;
  always_comb begin
    tx_level5 = '0;
    rx_level5 = '0;
    tx_level5[FIFO_AW:0] = tx_level;
    rx_level5[FIFO_AW:0] = rx_level;
  end
  assign tx_level_o = tx_level5;
  assign rx_level_o = rx_level5;

  // ----------------------------------------------------------------- tick
  wire tick = enable_i & ir_valid_q & (div_q == 16'd0);

  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) div_q <= '0;
    else if (!enable_i || !ir_valid_q) div_q <= '0;
    else if (div_q == 16'd0) div_q <= cfg_clkdiv_i;
    else div_q <= div_q - 16'd1;
  end

  // --------------------------------------------------------------- decode
  wire [31:0] ir     = mem_dout_i;
  wire [3:0]  op     = ir[31:28];
  wire [1:0]  cond   = ir[27:26];
  wire [3:0]  dly    = ir[25:22];
  wire        ss_en  = ir[21];
  wire [1:0]  ss_val = ir[20:19];

  wire active = tick & ~halted_q & (delay_q == 4'd0) & ~mphase_q;
  wire mfin   = tick & ~halted_q & mphase_q;      // second tick of ldm / stm
  wire skip   = (cond == 2'b01 && !t_q) || (cond == 2'b10 && t_q);

  // Register read ports. Every instruction that reads a register keeps its
  // number in the same place (bits 12:10 for the first, 9:7 for the second),
  // so the read starts as soon as the word leaves the memory, without waiting
  // for the opcode to be decoded. A pin number is always in bits 16:13.
  wire [2:0] ra_idx = ir[12:10];
  wire [2:0] rb_idx = ir[9:7];
  wire [3:0] pin_a  = ir[16:13];
  wire [15:0] ra_val = r_q[ra_idx*16 +: 16];
  wire [15:0] rb_val = r_q[rb_idx*16 +: 16];

  // ------------------------------------------------------------------ ALU
  wire [15:0] alu_b = (op == OP_ALUI) ? {6'd0, ir[9:0]} : rb_val;
  wire [3:0]  sh_amt = HAS_BSHIFT ? alu_b[3:0] : 4'd1;
  logic [15:0] alu_y;
  always_comb begin
    case (ir[18:16])
      3'd0:    alu_y = ra_val + alu_b;
      3'd1:    alu_y = ra_val - alu_b;
      3'd2:    alu_y = ra_val & alu_b;
      3'd3:    alu_y = ra_val | alu_b;
      3'd4:    alu_y = ra_val ^ alu_b;
      3'd5:    alu_y = ra_val << sh_amt;
      3'd6:    alu_y = ra_val >> sh_amt;
      default: alu_y = ra_val;
    endcase
  end
  wire alu_eq = (ra_val == alu_b);
  wire alu_lt = (ra_val < alu_b);

  // ------------------------------------------------------- shift helpers
  wire [3:0] sh_n     = {1'b0, ir[8:6]} + 4'd1;         // 1..8 bits
  wire [7:0] sh_mask  = 8'hFF >> (4'd8 - sh_n);
  wire       osr_empty = (osr_cnt_q >= cfg_pull_thresh_i);

  // Bits shifted out of osr, right-aligned.
  wire [7:0] out_bits = cfg_out_dir_i ? (osr_q >> (4'd8 - sh_n)) : (osr_q & sh_mask);
  wire [7:0] osr_sh   = cfg_out_dir_i ? (osr_q << sh_n) : (osr_q >> sh_n);
  wire [4:0] osr_cnt_sum = {1'b0, osr_cnt_q} + {1'b0, sh_n};
  wire [3:0] osr_cnt_sh  = (osr_cnt_sum > 5'd8) ? 4'd8 : osr_cnt_sum[3:0];

  // Bits shifted into isr, right-aligned.
  logic [7:0] in_bits;
  always_comb begin
    case (ir[18:17])
      2'd0:    in_bits = {8{pins_i[pin_a]}};
      2'd1:    in_bits = {8{t_q}};
      2'd2:    in_bits = ra_val[7:0];
      default: in_bits = 8'h00;
    endcase
  end
  wire [7:0] in_field = in_bits & sh_mask;
  wire [7:0] isr_sh   = cfg_in_dir_i ? ((isr_q << sh_n) | in_field)
                                     : ((isr_q >> sh_n) | (in_field << (4'd8 - sh_n)));
  wire [4:0] isr_cnt_sum = {1'b0, isr_cnt_q} + {1'b0, sh_n};
  wire [3:0] isr_cnt_sh  = (isr_cnt_sum > 5'd8) ? 4'd8 : isr_cnt_sum[3:0];

  // ------------------------------------------------------- mov source
  wire [7:0] status_byte = {tx_level_o[3:0], rx_full_o, rx_empty_o, tx_full_o, tx_empty_o};
  logic [15:0] mov_src;
  logic        mov_src_bad;
  always_comb begin
    mov_src_bad = 1'b0;
    case (ir[14:10])
      5'd0, 5'd1, 5'd2, 5'd3, 5'd4, 5'd5, 5'd6, 5'd7: mov_src = ra_val;
      5'd8:    mov_src = {8'd0, isr_q};
      5'd9:    mov_src = {8'd0, osr_q};
      5'd10:   mov_src = {8'd0, pins_i[7:0]};
      5'd11:   mov_src = {8'd0, pins_i[15:8]};
      5'd12:   mov_src = wtime_q;
      5'd13:   mov_src = crc_q[15:0];
      5'd14:   mov_src = crc_q[31:16];
      5'd15:   mov_src = 16'd0;
      5'd16:   mov_src = {{(16-AW){1'b0}}, lr_q};
      5'd17:   mov_src = {{(16-AW){1'b0}}, pc_q};
      5'd18:   mov_src = {8'd0, status_byte};
      5'd19:   mov_src = {8'd0, flags_i};
      default: begin
        mov_src = 16'd0;
        mov_src_bad = 1'b1;
      end
    endcase
  end
  logic [15:0] mov_val;
  always_comb begin
    case (ir[18:17])
      2'd1:    mov_val = ~mov_src;
      2'd2:    mov_val = {8'd0, mov_src[0], mov_src[1], mov_src[2], mov_src[3],
                          mov_src[4], mov_src[5], mov_src[6], mov_src[7]};
      default: mov_val = mov_src;
    endcase
  end

  // --------------------------------------------------------- data memory
  // Addresses wrap at the size of the memory, for the engine and for the host.
  wire [3:0]       dm_sum    = (ir[6] ? ra_val[3:0] : 4'd0) + ir[3:0];
  wire [DM_AW-1:0] dm_addr   = dm_sum[DM_AW-1:0];
  wire [DM_AW-1:0] dm_addr_h = dm_addr_i[DM_AW-1:0];
  wire [7:0]       dm_rd     = dm_q[dm_addr*8 +: 8];
  assign dm_rdata_o          = HOST_RB ? dm_q[dm_addr_h*8 +: 8] : 8'h00;
  // The upper address bits are not used when the memory is smaller than 16 bytes.
  wire _unused_dm = &{1'b0, dm_sum, dm_addr_i};

  // ------------------------------------------------------------ checksum
  logic        crc_step, crc_bit;
  wire  [31:0] crc_mask = 32'hFFFF_FFFF >> (6'd32 - cfg_crc_width_i);
  wire         crc_msb  = crc_q[cfg_crc_width_i[4:0] - 5'd1];
  wire         crc_fb   = (cfg_crc_dir_i ? crc_msb : crc_q[0]) ^ crc_bit;
  wire  [31:0] crc_poly = crc_fb ? cfg_crc_poly_i : 32'd0;
  wire  [31:0] crc_next = cfg_crc_dir_i ? (({crc_q[30:0], 1'b0} ^ crc_poly) & crc_mask)
                                        : ({1'b0, crc_q[31:1]} ^ crc_poly);

  // ------------------------------------------------------------ execute
  logic            stall, taken, bad, do_halt, mstart;
  logic [AW-1:0]   target;
  logic            rw_en;
  logic [2:0]      rw_idx;
  logic [15:0]     rw_data;
  logic            dm_we;
  logic            test, bitval, met, tmo, first;
  logic [15:0]     wt;
  logic [1:0]      wpins;

  wire [AW-1:0] pc_inc = pc_q + 1'b1;

  // ldm: the byte picked out of the word the memory block returned.
  logic [7:0] m_rdata;
  always_comb begin
    case (m_byte_q)
      2'd0:    m_rdata = mem_dout_i[7:0];
      2'd1:    m_rdata = mem_dout_i[15:8];
      2'd2:    m_rdata = mem_dout_i[23:16];
      default: m_rdata = mem_dout_i[31:24];
    endcase
  end

  always_comb begin
    // Defaults: everything holds.
    lr_d       = lr_q;
    isr_d      = isr_q;
    isr_cnt_d  = isr_cnt_q;
    osr_d      = osr_q;
    osr_cnt_d  = osr_cnt_q;
    t_d        = t_q;
    z_d        = z_q;
    c_d        = c_q;
    wtime_d    = wtime_q;
    snap_d     = snap_q;
    apwait_d   = apwait_q;
    level_d    = level_q;
    dir_d      = dir_q;
    crc_d      = crc_q;
    dbg_d      = dbg_q & ~dbg_clr_i;

    stall        = 1'b0;
    taken        = 1'b0;
    bad          = 1'b0;
    do_halt      = 1'b0;
    mstart       = 1'b0;
    target       = ir[AW-1:0];
    rw_en        = 1'b0;
    rw_idx       = 3'd0;
    rw_data      = 16'd0;
    dm_we        = 1'b0;
    tx_pop       = 1'b0;
    rx_push      = 1'b0;
    rx_push_data = isr_q;
    flag_set_o   = 8'd0;
    flag_clr_o   = 8'd0;
    crc_step     = 1'b0;
    crc_bit      = 1'b0;
    test         = 1'b0;
    bitval       = 1'b0;
    met          = 1'b0;
    tmo          = 1'b0;
    first        = ~stall_q;
    wt           = stall_q ? wtime_q : 16'd0;
    wpins        = {pins_i[ir[7:4]], pins_i[pin_a]};

    if (mfin && m_load_q) begin
      rw_en   = 1'b1;
      rw_idx  = m_rd_q;
      rw_data = {8'd0, m_rdata};
    end

    if (active && cond == 2'b11) begin
      bad = 1'b1;
    end else if (active && !skip) begin
      case (op)
        // ------------------------------------------------ jmp / tst
        OP_JMP: begin
          case (ir[17:14])
            4'd0:    test = 1'b1;
            4'd1:    test = (ra_val == 16'd0);
            4'd2:    test = (ra_val != 16'd0);
            4'd3:    test = (ra_val != 16'd0);
            4'd4:    test = z_q;
            4'd5:    test = ~z_q;
            4'd6:    test = c_q;
            4'd7:    test = ~c_q;
            4'd8:    test = t_q;
            4'd9:    test = ~t_q;
            4'd10:   test = ~osr_empty;
            4'd11:   test = osr_empty;
            4'd12:   test = tx_empty_o;
            4'd13:   test = ~tx_empty_o;
            4'd14:   test = rx_full_o;
            default: test = ~rx_full_o;
          endcase
          if (ir[17:14] == 4'd2) begin
            rw_en   = 1'b1;
            rw_idx  = ra_idx;
            rw_data = ra_val - 16'd1;
          end
          if (ir[18]) t_d = test;
          else taken = test;
        end

        // ---------------------------------------------- jbit / tbit
        OP_JBIT: begin
          bitval = ir[17] ? ra_val[pin_a] : pins_i[pin_a];
          test   = (bitval == ir[9]);
          if (ir[18]) t_d = test;
          else taken = test;
        end

        // ------------------------------------------------------ wait
        OP_WAIT: begin
          case (ir[18:17])
            2'd0: met = (pins_i[pin_a] == ir[8]);
            2'd1: begin
              if (first) snap_d = wpins;
              else met = (wpins != snap_q);
            end
            2'd2: met = (flags_i[ir[15:13]] == ir[8]);
            default: bad = 1'b1;
          endcase
          tmo = ir[9] && (wt == ra_val);
          if (met) begin
            if (ir[9]) t_d = 1'b0;
            wtime_d = wt;
          end else if (tmo) begin
            t_d     = 1'b1;
            wtime_d = wt;
          end else begin
            stall   = 1'b1;
            wtime_d = (wt == 16'hFFFF) ? wt : (wt + 16'd1);
          end
        end

        // -------------------------------------------------------- in
        OP_IN: begin
          if (!apwait_q) begin
            isr_d     = isr_sh;
            isr_cnt_d = isr_cnt_sh;
            crc_step  = ir[9];
            crc_bit   = in_bits[0];
          end
          if (cfg_autopush_i && isr_cnt_d >= cfg_push_thresh_i) begin
            if (!rx_full_o) begin
              rx_push      = 1'b1;
              rx_push_data = isr_d;
              isr_d        = 8'd0;
              isr_cnt_d    = 4'd0;
              apwait_d     = 1'b0;
            end else begin
              stall    = 1'b1;
              apwait_d = 1'b1;
            end
          end
        end

        // ------------------------------------------------------- out
        OP_OUT: begin
          if (cfg_autopull_i && osr_empty) begin
            // Nothing to shift: load a byte if there is one, run next tick.
            stall = 1'b1;
            if (!tx_empty_o) begin
              osr_d     = tx_head;
              osr_cnt_d = 4'd0;
              tx_pop    = 1'b1;
            end
          end else begin
            crc_step = ir[9];
            crc_bit  = out_bits[0];
            case (ir[18:17])
              2'd0: level_d[pin_a] = out_bits[0];
              2'd1: t_d = out_bits[0];
              2'd2: begin
                rw_en   = 1'b1;
                rw_idx  = ir[12:10];
                rw_data = {8'd0, out_bits};
              end
              default: ;
            endcase
            if (cfg_autopull_i && osr_cnt_sh >= cfg_pull_thresh_i && !tx_empty_o) begin
              osr_d     = tx_head;
              osr_cnt_d = 4'd0;
              tx_pop    = 1'b1;
            end else begin
              osr_d     = osr_sh;
              osr_cnt_d = osr_cnt_sh;
            end
          end
        end

        // ----------------------------------------------- push / pull
        OP_PP: begin
          if (!ir[18]) begin
            if (ir[16] && isr_cnt_q < cfg_push_thresh_i) begin
              // only-if: not enough bits yet, nothing to do
            end else if (!rx_full_o) begin
              rx_push   = 1'b1;
              isr_d     = 8'd0;
              isr_cnt_d = 4'd0;
            end else if (ir[17]) begin
              stall = 1'b1;
            end else begin
              isr_d     = 8'd0;
              isr_cnt_d = 4'd0;
              dbg_d[1]  = 1'b1;
            end
          end else begin
            if (ir[16] && !osr_empty) begin
              // only-if: osr still holds bits, nothing to do
            end else if (!tx_empty_o) begin
              osr_d     = tx_head;
              osr_cnt_d = 4'd0;
              tx_pop    = 1'b1;
            end else if (ir[17]) begin
              stall = 1'b1;
            end else begin
              dbg_d[0] = 1'b1;
            end
          end
        end

        // ------------------------------------------------------- mov
        OP_MOV: begin
          bad = mov_src_bad;
          if (ir[18:17] == 2'd3) t_d = ^mov_src;
          case (ir[9:5])
            5'd0, 5'd1, 5'd2, 5'd3, 5'd4, 5'd5, 5'd6, 5'd7: begin
              rw_en   = 1'b1;
              rw_idx  = ir[7:5];
              rw_data = mov_val;
            end
            5'd8: begin
              isr_d     = mov_val[7:0];
              isr_cnt_d = 4'd8;
            end
            5'd9: begin
              osr_d     = mov_val[7:0];
              osr_cnt_d = 4'd0;
            end
            5'd10: level_d[7:0]  = mov_val[7:0];
            5'd11: level_d[15:8] = mov_val[7:0];
            5'd12: dir_d         = mov_val[7:0];
            5'd13: crc_d[15:0]   = mov_val;
            5'd14: crc_d[31:16]  = mov_val;
            5'd15: ;
            5'd16: lr_d = mov_val[AW-1:0];
            5'd17: begin
              taken  = 1'b1;
              target = mov_val[AW-1:0];
            end
            default: bad = 1'b1;
          endcase
        end

        // ------------------------------------------------------- irq
        OP_IRQ: begin
          case (ir[18:17])
            2'd0: flag_set_o[ir[15:13]] = 1'b1;
            2'd1: flag_clr_o[ir[15:13]] = 1'b1;
            2'd2: begin
              if (first) begin
                flag_set_o[ir[15:13]] = 1'b1;
                stall = 1'b1;
              end else if (flags_i[ir[15:13]]) begin
                stall = 1'b1;
              end
            end
            default: bad = 1'b1;
          endcase
        end

        // ------------------------------------------------------- set
        OP_SET: begin
          rw_en   = 1'b1;
          rw_idx  = ir[18:16];
          rw_data = ir[15:0];
        end

        // ------------------------------------------------------- ALU
        OP_ALUR, OP_ALUI: begin
          if (ir[18:16] == 3'd7) begin
            z_d = alu_eq;
            c_d = alu_lt;
          end else begin
            rw_en   = 1'b1;
            rw_idx  = ir[15:13];
            rw_data = alu_y;
          end
        end

        // --------------------------------------------------- ld / st
        // Bit 18 = 0: the flip-flop data memory, one tick. Bit 18 = 1
        // ("ldm" / "stm"): one byte of the memory block, at the byte address
        // in the base register; two ticks.
        OP_LD: begin
          if (ir[18]) mstart = 1'b1;
          else begin
            rw_en   = 1'b1;
            rw_idx  = ir[15:13];
            rw_data = {8'd0, dm_rd};
          end
        end
        OP_ST: begin
          if (ir[18]) mstart = 1'b1;
          else dm_we = 1'b1;
        end

        // ------------------------------------------------ call / ret
        OP_CALL: begin
          taken = 1'b1;
          if (ir[18]) target = lr_q;
          else lr_d = pc_inc;
        end

        // ------------------------------------------------------- pin
        OP_PIN: begin
          case (ir[18:17])
            2'd0: level_d[pin_a] = ir[12];
            2'd1: level_d[pin_a] = ~level_q[pin_a];
            2'd2: if (ir[16]) dir_d[ir[15:13]] = ir[12];
            default: bad = 1'b1;
          endcase
        end

        // ------------------------------------------------------ halt
        OP_HALT: do_halt = 1'b1;
        default: do_halt = 1'b1;
      endcase
    end

    // Side-set: applied whenever the instruction is tried, also when it is
    // skipped or stalls. It overrides a write by the instruction itself.
    if (active && cond != 2'b11 && ss_en) begin
      if (cfg_side0_i[4]) begin
        if (!cfg_side0_i[5]) level_d[cfg_side0_i[3:0]] = ss_val[0];
        else if (cfg_side0_i[3]) dir_d[cfg_side0_i[2:0]] = ss_val[0];
      end
      if (cfg_side1_i[4]) begin
        if (!cfg_side1_i[5]) level_d[cfg_side1_i[3:0]] = ss_val[1];
        else if (cfg_side1_i[3]) dir_d[cfg_side1_i[2:0]] = ss_val[1];
      end
    end

    if (crc_step) crc_d = crc_next;
    if (!HAS_CRC) crc_d = '0;
  end

  // An illegal word or a halt stops the engine without advancing.
  wire stop_now = active & (bad | do_halt);
  wire advance  = active & ~stall & ~bad & ~do_halt & ~mstart;

  wire [AW-1:0] next_pc = taken ? target : pc_inc;

  // First fetch after the engine is enabled (or its pc was changed).
  wire fetch_first = enable_i & ~ir_valid_q & ~halted_q;

  // The memory block has one port. Normally it fetches the next instruction.
  // On the first tick of ldm / stm it reads or writes the data byte instead
  // (word address = byte address / 4), and on the second tick it fetches the
  // instruction after.
  wire          m_store = mstart & (op == OP_ST);
  wire [AW-1:0] m_addr  = ra_val[AW+1:2];
  logic [31:0]  m_bm;
  always_comb begin
    case (ra_val[1:0])
      2'd0:    m_bm = 32'h0000_00FF;
      2'd1:    m_bm = 32'h0000_FF00;
      2'd2:    m_bm = 32'h00FF_0000;
      default: m_bm = 32'hFF00_0000;
    endcase
  end

  assign mem_ren_o  = fetch_first | advance | mfin | (mstart & ~m_store);
  assign mem_wen_o  = m_store;
  assign mem_din_o  = {4{rb_val[7:0]}};
  assign mem_bm_o   = m_bm;
  assign mem_addr_o = fetch_first ? pc_q :
                      mfin        ? pc_inc :
                      mstart      ? m_addr : next_pc;

  always_comb begin
    pc_d      = pc_q;
    delay_d   = delay_q;
    stall_d   = stall_q;
    halted_d  = halted_q;
    illegal_d = illegal_q;
    if (mfin) begin
      pc_d    = pc_inc;
      delay_d = m_dly_q;
      stall_d = 1'b0;
    end else if (advance) begin
      pc_d    = next_pc;
      delay_d = dly;
      stall_d = 1'b0;
    end else if (active && stall) begin
      stall_d = 1'b1;
    end else if (tick && !halted_q && delay_q != 4'd0) begin
      delay_d = delay_q - 4'd1;
    end
    if (stop_now) begin
      halted_d  = 1'b1;
      illegal_d = bad;
    end
  end

  // ------------------------------------------------------------ registers
  always_ff @(posedge clk or negedge rst_ni) begin
    if (!rst_ni) begin
      pc_q       <= '0;
      lr_q       <= '0;
      r_q        <= '0;
      isr_q      <= '0;
      isr_cnt_q  <= '0;
      osr_q      <= '0;
      osr_cnt_q  <= 4'd8;
      t_q        <= 1'b0;
      z_q        <= 1'b0;
      c_q        <= 1'b0;
      wtime_q    <= '0;
      snap_q     <= '0;
      stall_q    <= 1'b0;
      apwait_q   <= 1'b0;
      level_q    <= '0;
      dir_q      <= '0;
      crc_q      <= '0;
      delay_q    <= '0;
      halted_q   <= 1'b0;
      illegal_q  <= 1'b0;
      dbg_q      <= '0;
      ir_valid_q <= 1'b0;
      mphase_q   <= 1'b0;
      m_load_q   <= 1'b0;
      m_rd_q     <= '0;
      m_byte_q   <= '0;
      m_dly_q    <= '0;
    end else begin
      // ldm / stm. Stopping the engine between the two ticks abandons the
      // access; the instruction runs again when the engine restarts.
      if (restart_i || pc_we_i || !enable_i) mphase_q <= 1'b0;
      else if (mstart)                       mphase_q <= 1'b1;
      else if (mfin)                         mphase_q <= 1'b0;
      if (mstart) begin
        m_load_q <= (op == OP_LD);
        m_rd_q   <= ir[15:13];
        m_byte_q <= ra_val[1:0];
        m_dly_q  <= dly;
      end

      // Program counter and the "instruction on mem_dout_i is valid" flag.
      if (restart_i) begin
        pc_q       <= '0;
        ir_valid_q <= 1'b0;
      end else if (pc_we_i) begin
        pc_q       <= pc_wdata_i;
        ir_valid_q <= 1'b0;
      end else if (!enable_i) begin
        ir_valid_q <= 1'b0;
      end else begin
        pc_q <= pc_d;
        if (fetch_first) ir_valid_q <= 1'b1;
      end

      if (restart_i) begin
        lr_q      <= '0;
        isr_q     <= '0;
        isr_cnt_q <= '0;
        osr_q     <= '0;
        osr_cnt_q <= 4'd8;
        t_q       <= 1'b0;
        z_q       <= 1'b0;
        c_q       <= 1'b0;
        wtime_q   <= '0;
        stall_q   <= 1'b0;
        apwait_q  <= 1'b0;
        delay_q   <= '0;
        halted_q  <= 1'b0;
        illegal_q <= 1'b0;
        dbg_q     <= '0;
        crc_q     <= '0;
      end else begin
        lr_q      <= lr_d;
        isr_q     <= isr_d;
        isr_cnt_q <= isr_cnt_d;
        osr_q     <= osr_d;
        osr_cnt_q <= osr_cnt_d;
        t_q       <= t_d;
        z_q       <= z_d;
        c_q       <= c_d;
        wtime_q   <= wtime_d;
        snap_q    <= snap_d;
        stall_q   <= stall_d;
        apwait_q  <= apwait_d;
        delay_q   <= delay_d;
        halted_q  <= halted_d;
        illegal_q <= illegal_d;
        dbg_q     <= dbg_d;
        crc_q     <= crc_d;
      end

      level_q <= level_d;
      dir_q   <= dir_d;

      // Registers: the engine's write wins over a host write on the same clock.
      if (rw_en) r_q[rw_idx*16 +: 16] <= rw_data;
      else if (hreg_we_i) r_q[{hreg_sel_i, hreg_hi_i}*8 +: 8] <= hreg_wdata_i;

    end
  end

  // Data memory: the engine's write wins over a host write on the same clock.
  pe_lmem #(.AW(DM_AW)) u_dm (
      .clk(clk), .rst_ni(rst_ni),
      .we_i   (dm_we | dm_we_i),
      .waddr_i(dm_we ? dm_addr : dm_addr_h),
      .wdata_i(dm_we ? rb_val[7:0] : dm_wdata_i),
      .q_o    (dm_q)
  );

  // -------------------------------------------------------------- outputs
  assign pin_level_o  = level_q;
  assign pin_dir_o    = dir_q;
  assign hreg_rdata_o = HOST_RB ? r_q[hreg_sel_i*16 +: 16] : 16'h0000;
  assign pc_o         = pc_q;
  assign stalled_o    = stall_q;
  assign halted_o     = halted_q;
  assign illegal_o    = illegal_q;
  assign debug_o      = dbg_q;
  assign crc_o        = crc_q;

endmodule

`default_nettype wire
