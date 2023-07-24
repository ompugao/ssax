import os
import time

import hydra
import numpy as np
from matplotlib import pyplot as plt
from matplotlib import animation, rc
rc('animation', html='html5')

from omegaconf import DictConfig, OmegaConf
import jax
import jax.numpy as jnp

from ssax.objectives.visualization import plot_objective
import ssax.objectives
from ssax.objectives import ObjectiveFn
import ssax.ss.initializer
import ssax.ss.linear_solver
import ssax.ss.solver
import ssax.ss.epsilon_scheduler


@hydra.main(version_base=None, config_path="../configs", config_name="config")
def main(cfg: DictConfig):
    # Set data directory
    data_dir = cfg.data_dir
    if data_dir is None:
        data_dir = os.path.join(ssax.DATA_DIR, cfg.experiment.name)

    # Set log directory
    logs_dir = cfg.logs_dir
    if logs_dir is None:
        logs_dir = os.path.join(ssax.LOGS_DIR, cfg.experiment.name, time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(logs_dir, exist_ok=True)

    if cfg.gpu:
        os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["XLA_FLAGS"] = "--xla_force_host_platform_device_count=16"

    seed = cfg.experiment.seed
    rng = jax.random.PRNGKey(seed)

    # Load task objective function
    task_cls = getattr(ssax.objectives, cfg.experiment.task.name)
    task: ObjectiveFn = task_cls(**cfg.experiment.task.kwargs)

    # Sample initializer
    init_cls = getattr(ssax.ss.initializer, cfg.experiment.initializer.name)
    if task.bounds is not None:
        cfg.experiment.initializer.kwargs.bounds = task.bounds
    initializer = init_cls(rng=rng, **cfg.experiment.initializer.kwargs)

    # Linear solver
    solver_cls = getattr(ssax.ss.linear_solver, cfg.experiment.linear_solver.name)
    linear_ot_solver = solver_cls(**cfg.experiment.linear_solver.kwargs)

    # Epislon scheduler
    epsilon_scheduler_cls = getattr(ssax.ss.epsilon_scheduler, cfg.experiment.epsilon_scheduler.name)
    epsilon_scheduler = epsilon_scheduler_cls(**cfg.experiment.epsilon_scheduler.kwargs)

    # global optimizer  # TODO: make a base class for global optimizers
    global_optimizer_cls = getattr(ssax.ss.solver, cfg.experiment.optimizer.name)
    global_optimizer = global_optimizer_cls(
        objective_fn=task,
        linear_ot_solver=linear_ot_solver,
        epsilon=epsilon_scheduler,
        rng=rng,
        store_history=cfg.save_video,  # NOTE: only store history if we are saving video
        **cfg.experiment.optimizer.kwargs
    )

    X_init = initializer(cfg.experiment.num_points)
    tic = time.time()
    res = global_optimizer.iterations(X_init)
    toc = time.time()
    print(f"Optimization time: {toc - tic:.2f} s")

    # NOTE: this is a hack getting converged iteration index
    cid = jnp.where(res.linear_convergence == -1)[0]
    if len(cid) == 0:
        converged_at = res.linear_convergence.shape[0]
    else:
        converged_at = cid.min()

    # Plotting
    if task.bounds is None:
        bounds = [[-10.0, 10.0], [-10.0, 10.0]]
    else:
        bounds = task.bounds
    fig, ax = plt.subplots()
    ax.set_xlim(*bounds[0])
    ax.set_ylim(*bounds[1])
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title(f"{cfg.experiment.name}")
    plot_objective(objective_fn=task, ax=ax)
    text = ax.text(bounds[0][1], bounds[1][1] + 0.5, f'Iters {0}', style='italic')
    scatter = ax.scatter(X_init[:, 0], X_init[:, 1], s=3)
    fig.tight_layout()

    if cfg.save_video:
        X_hist = res.X_history
        def plot_particle(iter):
            """ Plots the objective function in 2D """
            X = X_hist[iter]
            scatter.set_offsets(X[:, :2])
            text.set_text(f'Iters {iter}')
            return scatter, text
        anim = animation.FuncAnimation(fig, plot_particle, frames=converged_at, interval=100, blit=True)
        anim_name = os.path.join(logs_dir, f"{cfg.experiment.name}_{cfg.experiment.num_points}.gif")
        anim.save(anim_name, writer='imagemagick', fps=20)

    if cfg.plotting:
        X = res.X
        scatter.set_offsets(X[:, :2])
        text.set_text(f'Iters {converged_at}')
        # Save figure
        fig_name = os.path.join(logs_dir, f"{cfg.experiment.name}_{cfg.experiment.num_points}.png")
        fig.savefig(fig_name, dpi=300)

    # Save results
    if cfg.save_result:
        res_name = os.path.join(logs_dir, f"{cfg.experiment.name}_{cfg.experiment.num_points}.npz")
        np.savez(res_name, **res)


if __name__ == "__main__":
    main()
