public class Foo
{
    public void method(int[] xs)
    {
        for (int x : xs) {
            if (x == 0) {
                continue;
            }
            doStuff(x);
        }
    }
}
