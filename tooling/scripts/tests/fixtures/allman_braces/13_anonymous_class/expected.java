public class Foo
{
    public void method()
    {
        Runnable r = new Runnable() {
            public void run()
            {
                doIt();
            }
        };
    }
}
