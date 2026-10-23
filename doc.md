Train a high-performance, domain-specialized bi-encoder embedding model optimized exclusively for e-commerce, retail discovery, and search.

Primary Use-Cases & Objectives:
- Query → Product Retrieval (Title + Rich Attributes + Bullet Points + Description + Category Path)
- Semantic Product-to-Product Similarity & Cross-sell/Upsell Recommendation
- Intent / Natural Language Review → Product Matching ("warm winter jacket for hiking under $200")
- Query Rewriting, Expansion, and Conversational Search Intent Mapping
- Hybrid Dense + Sparse / Multi-Vector (ColBERT-style late-interaction or SPLADE-integrated) Retrieval
- Robust handling of noisy, short, typo-ridden queries, brand synonyms, SKU variations (size/color/material), and attribute-heavy text.

Model Architecture & Specifications:
- Parameter Scale: 100M–300M parameters (Sweet spot for high-QPS, low-latency enterprise CPU/GPU serving).
- Depth / Hidden Size: 10–12 layers, hidden dimension 768–1024, embedding dimension 768 (with native Matryoshka support down to 64 dims).
- Context Window & Curriculum: Progressive context curriculum starting at 512 → 1024 → 2048 tokens (optional 4096 for long-form reviews and rich specification sheets).
- Core Components: 
  - Modern Transformer encoder (or causal LLM adapted to bi-encoder via custom pooling).
  - Grouped-Query Attention (GQA) for memory-efficient inference.
  - SwiGLU activation functions and Pre-RMSNorm with QK-LayerNorm to stabilize large-batch training.
  - RoPE (Rotary Position Embeddings) with YaRN or NTK-aware scaling for robust length extrapolation.
  - Pooling: Weighted mean-pooling or last-token (EOS) pooling optimized for bi-encoders.
  - Matryoshka Representation Learning (MRL) / SpecMRL for flexible, multi-granularity dimension truncation (32, 64, 128, 256, 512, 768).

Pretraining & Fine-Tuning Loss Strategy:
- Phase 1 (Domain-Adaptive Pretraining - DAPT): RetroMAE-v3 or DupMAE-style masked autoencoding tailored for retrieval. This reconstructs full product descriptions and attributes from heavily masked inputs, building deep lexical-semantic alignment.
- Phase 2 (Supervised Fine-Tuning - SFT): Cached Multiple Negatives Ranking Loss (CachedMNRL / InfoNCE) with extreme batch sizes (effective global batch size $\ge 4096$) and hard-negative mining (BM25 + iterative ANCE + Cross-Encoder reranking).
- False-Negative Mitigation: Explicit margin-based false-negative masking and taxonomy-aware filtering to prevent penalizing the model when it retrieves a valid size/color variant of the target product.

Datasets & Data Engineering:
- Domain Primary: thebajajra/Ecom-niverse (~3M records), Amazon Reviews 2023 (titles + verified reviews), Amazon ESCI (Exact / Substitute / Complement / Irrelevant relevance labels), and structured product catalogs (titles, attributes, breadcrumbs).
- Synthetic Augmentation: LLM-generated hard queries, typo injection, brand synonym swaps, and attribute-shuffled negatives.
- General Robustness: 10% mix of HuggingFaceFW/fineweb-edu and Wikipedia to prevent catastrophic forgetting of general language syntax.
- Pipeline: Sharded Parquet datasets streamed via `IterableDataset`, utilizing dynamic sequence packing to eliminate padding waste.

Engineering & Tech Stack:
- Distributed Framework: PyTorch DDP / FSDP via `torchrun`, Accelerate, or DeepSpeed ZeRO-2/3.
- Performance Optimizations: `torch.compile(mode="reduce-overhead")`, bfloat16 + TF32 precision, FlashAttention-2 / SDPA, fused AdamW optimizers, and gradient checkpointing.
- Configuration & Tracking: Centralized configuration via Hydra (`config.yaml`), TensorBoard/Wandb structured logging tracking tokens/sec/GPU, active FLOPs, step loss, and evaluation checkpoints.
- Production Tooling: Fully compatible with SentenceTransformers (`SentenceTransformer` class, standard encode API, custom evaluation hooks, and automatic model card generation).

Training Curriculum & Phases:
- Phase 0 (Initialization): Cold start from scratch or initialize from a strong open embedder (e.g., Qwen3-Embedding-0.6B, BGE-M3, or Granite-Embedding) for faster convergence.
- Phase 1 (DAPT): RetroMAE pretraining on mixed ecom catalog + general web text using dynamic masking ratios (e.g., 30–50%).
- Phase 2 (SFT): Contrastive learning using MNRL, incorporating hard negatives, in-batch negatives, and margin adjustments for variant discrimination.
- Phase 3 (Refinement): MRL loss integration, multi-vector head attachment, or task-specific distillation.

Rigorous Evaluation Suite:
- Primary Retail Benchmarks: Amazon ESCI dataset (nDCG@10, MRR, Recall@K across Exact and Substitute tiers) and internal catalog search test sets.
- Secondary Benchmarks: MTEB English Retrieval and STS subsets to ensure zero regression on general semantic tasks.
- System Metrics: End-to-end query latency (ms), throughput (QPS) under FP16/INT8/Binary quantization, and MRL truncation degradation curves.

Deliverables:
- Complete, modular training codebase (data loaders, custom loss implementations, training loops).
- Evaluation harness for MTEB and custom e-commerce retrieval metrics.
- Fine-tuned model weights converted to SentenceTransformers format, accompanied by a comprehensive technical implementation report and model card.
  
  
## Critical Bottlenecks & Optimization Tips for 4× A100 80GB

1. **Avoid Data Loader Bottlenecks (CPU $\rightarrow$ GPU Transfer):**
    
    - Pre-tokenize and convert datasets into **sharded Parquet / Arrow datasets** before starting training.
        
    - Tokenizing dynamically on the fly during training can cause CPU bottlenecks that drop GPU utilization down to <40%.
        
2. **Use Sequence Packing (Zero Padding Waste):**
    
    - Unpadded packed sequences (concatenating shorter texts with `attn_mask` position offsets) will increase training speed by **1.8× to 2.5×** on e-commerce catalogs where text length varies wildly (e.g., 10-token titles vs. 500-token descriptions).
        
3. **GradCache / CachedMNRL is Mandatory for 4 GPUs:**
    
    - Fitting a batch size of $4,096+$ natively in GPU memory requires a large cluster (32+ GPUs).
        
    - By using **GradCache** (computing embeddings in small chunks, gathering gradients, and updating without holding all activation maps in VRAM), you can run massive contrastive batch sizes seamlessly on a single 4× A100 node without OOM errors.