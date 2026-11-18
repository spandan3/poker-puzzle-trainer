import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { GoalInput } from './GoalInput'

function setup(onGoal = vi.fn(async () => true), goal = 3) {
  const user = userEvent.setup()
  const view = render(<GoalInput goal={goal} onGoal={onGoal} />)
  return { user, onGoal, ...view }
}

const input = () => screen.getByRole('spinbutton', { name: 'Puzzles per day' })

describe('GoalInput', () => {
  it('commits a valid goal on Enter and on blur', async () => {
    const { user, onGoal } = setup()
    await user.clear(input())
    await user.type(input(), '12{Enter}')
    expect(onGoal).toHaveBeenLastCalledWith(12)
    await user.clear(input())
    await user.type(input(), '15')
    await user.tab()
    expect(onGoal).toHaveBeenLastCalledWith(15)
  })

  it.each(['0', '501', '2.5', ''])('rejects %j with a message and saves nothing', async (text) => {
    const { user, onGoal } = setup()
    await user.clear(input())
    if (text !== '') await user.type(input(), text)
    await user.tab()
    expect(onGoal).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a whole number from 1 to 500')
    expect(input()).toHaveAttribute('aria-invalid', 'true')
  })

  it('does not save an unchanged goal', async () => {
    const { user, onGoal } = setup()
    await user.click(input())
    await user.tab()
    expect(onGoal).not.toHaveBeenCalled()
  })

  it('follows a goal that changes from outside', () => {
    const { rerender } = setup()
    rerender(<GoalInput goal={8} onGoal={async () => true} />)
    expect(input()).toHaveValue(8)
  })
})
